/* PaperPull.app's main executable.

    clang -fobjc-arc -O2 -arch <ARCH> -mmacosx-version-min=<MACOS_MIN> \
        -framework Cocoa -framework WebKit -o Contents/MacOS/PaperPull launcher.m

WHAT IT DOES

Double-clicking PaperPull opens a window of its own showing the control panel,
with a Dock icon and the usual menus. No Terminal window and no browser tab.
Behind the window it runs the same panel paperpull-panel.sh runs, the bundled
Python serving gui/app.py on 127.0.0.1, and shows it in a WKWebView. The panel,
its page and the apps do not know the difference. Quitting stops the panel.

It is compiled on the build machine by packaging/build_macos.py rather than
being a script, because notarization requires the main executable to be a
Mach-O binary carrying the hardened runtime.

HOW, AND WHY THIS WAY

The panel. The bundled python3 runs uvicorn exactly as paperpull-panel.sh does,
from Resources, with PYTHONNOUSERSITE and the bytecode cache sent to
~/Library/Caches. Its output is appended to ~/Library/Logs/PaperPull/panel.log,
started afresh once it passes 5 MB, since there is no Terminal to read it in.

It is started with posix_spawn rather than NSTask for one reason: it is put in
a process group of its own. The panel starts the apps' runs, and they start a
browser for sign-in. Closing the Terminal window used to hang up that whole
group, so quitting here signals the whole group too, SIGTERM and then, after
5 seconds, SIGKILL. Nothing the panel started outlives a normal quit.

The port. 8765, the panel's usual port, so the page keeps what it stored in
the web view (an origin includes its port). When something else is listening
there, the OS picks a free one. The page is always loaded as 127.0.0.1, the
one name the panel's Host check is sure to accept. PAPERPULL_PORT overrides
the choice, for tests.

The launcher listens on that port itself and hands the listening socket to
uvicorn with --fd, rather than finding a port free and leaving uvicorn to take
it a second later. In that second any other program, another user's too,
could take the port first, answer the readiness poll and be shown in the
panel's window, at the panel's origin, with the panel's storage. Now only the
launcher and the panel hold the socket, so whatever answers on it is the
panel. The launcher keeps it until it quits, so a restarted panel is given
the same one, at the same port, and nobody can take it in between.

A panel left behind. If the launcher itself crashes, the panel it started
keeps running, and its pid is in ~/Library/Application Support/PaperPull/
panel.pid, with the launcher's own pid on the line after it. The next start
stops that process, but only when that launcher is gone, since a second copy
of the app (open -n, or the self-test run while the app is open) must not
take the first one's live panel away, and only after reading its command line
and finding this bundle's own Resources/gui in it, so a recycled pid can never
take some other program down with it. The pidfile is removed at quit only by
the launcher it names.

The window. It shows a small "Starting" page at once and goes to the panel as
soon as GET / answers 200, polled off the main thread every 150 ms. A panel
that exits before then is reported with its log a click away, and one not up
after 45 seconds is too, with the choice to keep waiting for it. One that
exits with status 0 later was stopped on purpose, say to restart for an
update, and the app quits quietly, after stopping whatever it left in its
group. Any other exit offers to restart it.

What the web view may show. Only the panel, at http://127.0.0.1:<port>, and
the blank starting page. Every other link, every target=_blank link and every
window.open goes to the default browser, and only when it is http, https or
mailto. Anything else is dropped, so nothing the page links to can turn the
panel's own window into somebody else's page.

Downloads. Every download the page makes is a fetch of an /api/.../download or
/api/history/export answer, turned into a blob: URL and clicked as
<a download>. WKDownload (macOS 11.3) handles that, asking where to save in a
sheet. On 11.0 to 11.2 there is no WKDownload, and a blob: URL means nothing
outside the page, so a small script catches the same click, reads the blob and
hands the bytes over to be saved the same way. A download by plain navigation,
which the page does not make today, goes to the default browser there.

TESTS

PAPERPULL_LAUNCHER_SELFTEST=ready starts the panel, waits for it, prints
"READY http://127.0.0.1:<port>", stops it and exits 0. =window does the same
through the real window, without taking focus, and prints the page's
"WINDOW title=<title>" once it has loaded. Either exits 1, with the reason on
stderr, on any failure or after 60 seconds.
*/
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <libproc.h>
#include <limits.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <spawn.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static const int kDefaultPort = 8765;
static const double kPollEvery = 0.15, kReadyWithin = 45, kSelfTestWithin = 60, kStopGrace = 5;
static const off_t kLogLimit = 5 * 1024 * 1024;
static NSString *const kGuideURL = @"https://paperpull.net/guide.html";

#pragma mark - Small helpers in plain C

static double Now(void) { return [NSDate timeIntervalSinceReferenceDate]; }

static struct sockaddr_in Loopback(int port) {
    struct sockaddr_in a = {0};
    a.sin_len = sizeof a; a.sin_family = AF_INET; a.sin_port = htons((uint16_t)port);
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    return a;
}

static BOOL SomebodyListens(int port) {
    struct sockaddr_in a = Loopback(port);
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) return NO;
    BOOL listening = connect(s, (struct sockaddr *)&a, sizeof a) == 0;
    close(s);
    return listening;
}

// A socket listening on 127.0.0.1 at this port, 0 meaning any free one, or -1.
// See "The port" above. It is close-on-exec like everything else the launcher
// opens, and only the panel is given it. A port that cannot be bound only
// because a closed connection lingers in TIME_WAIT is still fine, so a refused
// bind is followed by a connect to tell that apart from a port somebody really
// listens on, and only then is it bound again with SO_REUSEADDR. TCP_NODELAY
// is set here because uvicorn takes the socket for a Unix one (it opens --fd
// as AF_UNIX) and would not set it on the connections, which inherit it.
static int ListenOn(int port) {
    struct sockaddr_in a = Loopback(port);
    for (int reuse = 0; reuse <= 1; reuse++) {
        int s = socket(AF_INET, SOCK_STREAM, 0), one = 1;
        if (s < 0) return -1;
        fcntl(s, F_SETFD, FD_CLOEXEC);
        setsockopt(s, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        if (reuse) setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
        if (bind(s, (struct sockaddr *)&a, sizeof a) == 0 && listen(s, 128) == 0) return s;
        BOOL inUse = errno == EADDRINUSE;
        close(s);
        if (!inUse || port == 0 || SomebodyListens(port)) return -1;
    }
    return -1;
}

static int SocketPort(int s) {
    struct sockaddr_in a = {0};
    socklen_t n = sizeof a;
    return getsockname(s, (struct sockaddr *)&a, &n) == 0 ? ntohs(a.sin_port) : 0;
}

// The status code GET / answers with, or -1. A raw socket rather than
// NSURLSession, so no proxy setting or transport policy can get in between.
static int HTTPStatus(int port) {
    struct sockaddr_in a = Loopback(port);
    int s = socket(AF_INET, SOCK_STREAM, 0), status = -1;
    if (s < 0) return -1;
    struct timeval tv = {2, 0};
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
    int one = 1;
    setsockopt(s, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
    if (connect(s, (struct sockaddr *)&a, sizeof a) == 0) {
        char req[128], buf[64] = {0};
        int n = snprintf(req, sizeof req, "GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n", port);
        if (write(s, req, (size_t)n) == n && read(s, buf, sizeof buf - 1) > 12 && strncmp(buf, "HTTP/1.", 7) == 0)
            status = atoi(buf + 9);
    }
    close(s);
    return status;
}

// Whether one of the process's arguments is exactly `want`. KERN_PROCARGS2
// lays out argc, the executable path, padding, then argv.
static BOOL ProcessHasArgument(pid_t pid, const char *want) {
    int mib[3] = {CTL_KERN, KERN_PROCARGS2, pid}, argmax = 0;
    size_t size = sizeof argmax;
    int mibmax[2] = {CTL_KERN, KERN_ARGMAX};
    if (sysctl(mibmax, 2, &argmax, &size, NULL, 0) != 0 || argmax <= 0) return NO;
    char *buf = malloc((size_t)argmax);
    size = (size_t)argmax;
    BOOL found = NO;
    if (buf && sysctl(mib, 3, buf, &size, NULL, 0) == 0 && size > sizeof(int)) {
        int argc; memcpy(&argc, buf, sizeof argc);
        char *p = buf + sizeof argc, *end = buf + size;
        p += strnlen(p, (size_t)(end - p));            // the executable path
        while (p < end && *p == '\0') p++;             // its padding
        for (int i = 0; i < argc && p < end; i++) {
            size_t len = strnlen(p, (size_t)(end - p));
            if (len == strlen(want) && memcmp(p, want, len) == 0) { found = YES; break; }
            p += len + 1;
        }
    }
    free(buf);
    return found;
}

// Whether pid is a live process running the executable at `path`. A process
// whose path cannot be read is not one of the launcher's, which runs as the
// same user and can always read its own.
static BOOL ProcessRuns(pid_t pid, const char *path) {
    char have[PROC_PIDPATHINFO_MAXSIZE], realHave[PATH_MAX], realWant[PATH_MAX];
    if (pid <= 1 || (kill(pid, 0) != 0 && errno == ESRCH)) return NO;
    if (proc_pidpath(pid, have, sizeof have) <= 0) return NO;
    return realpath(have, realHave) && realpath(path, realWant) && strcmp(realHave, realWant) == 0;
}

static BOOL GroupGone(pid_t pgid) { return killpg(pgid, 0) != 0 && errno == ESRCH; }

// Every stop of a panel's group goes through this one queue, so a quit waits
// for a stop already under way, after the panel exited, instead of racing it
// and leaving before its SIGKILL.
static dispatch_queue_t StopQueue(void) {
    static dispatch_queue_t q;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ q = dispatch_queue_create("PaperPull.stop", DISPATCH_QUEUE_SERIAL); });
    return q;
}

// SIGTERM to the whole group, up to kStopGrace seconds for it to empty, then
// SIGKILL to whatever is left. Blocks, so it is only ever called off the main
// thread. Once the group is empty its id is not touched again, since the
// system may then hand that number to a new process.
static void StopGroup(pid_t pgid) {
    if (pgid <= 1 || GroupGone(pgid)) return;
    killpg(pgid, SIGTERM);
    double deadline = Now() + kStopGrace;
    while (Now() < deadline && !GroupGone(pgid)) usleep(50000);
    if (!GroupGone(pgid)) killpg(pgid, SIGKILL);
    deadline = Now() + 2;
    while (Now() < deadline && !GroupGone(pgid)) usleep(20000);
}

// What a suggested download name may be: a plain name, no folders, nothing
// hidden, nothing that cannot be typed.
static NSString *PlainFileName(NSString *name) {
    NSMutableString *s = [NSMutableString string];
    for (NSUInteger i = 0; i < name.length; i++) {
        unichar c = [name characterAtIndex:i];
        [s appendString:(c < 0x20 || c == 0x7f || c == '/' || c == ':' || c == '\\')
            ? @"-" : [NSString stringWithCharacters:&c length:1]];
    }
    NSString *t = [s stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@". \t"]];
    return t.length ? t : @"download";
}

// Where to save a download, asked as a sheet on the window. The save panel
// itself asks before replacing a file that is there.
static void AskWhereToSave(NSWindow *window, NSString *suggested, void (^done)(NSURL *url)) {
    NSSavePanel *panel = [NSSavePanel savePanel];
    panel.nameFieldStringValue = PlainFileName(suggested ?: @"");
    panel.directoryURL = [[NSFileManager defaultManager] URLsForDirectory:NSDownloadsDirectory
                                                                inDomains:NSUserDomainMask].firstObject;
    panel.extensionHidden = NO;
    void (^answer)(NSModalResponse) = ^(NSModalResponse r) { done(r == NSModalResponseOK ? panel.URL : nil); };
    if (window) [panel beginSheetModalForWindow:window completionHandler:answer];
    else answer([panel runModal]);
}

static void SayOnWindow(NSWindow *window, NSString *what, NSString *info) {
    NSAlert *a = [NSAlert new];
    a.messageText = what; a.informativeText = info ?: @"";
    if (window) [a beginSheetModalForWindow:window completionHandler:nil]; else [a runModal];
}

#pragma mark - The panel process

// One run of the panel. `done` and `status` are set by its waiter thread.
// `pgid` is its process group, the same number as its pid, and `groupGone`
// is set once that group has been seen empty, after which the number is never
// signalled again.
@interface PPChild : NSObject
@property (atomic) pid_t pid, pgid;
@property (atomic) int port, status;
@property (atomic) BOOL done, groupGone;
@end
@implementation PPChild
@end

// The one way a panel's group is stopped, on StopQueue, and so never twice at
// once. It does nothing for a group already seen empty, and stops one that
// still has members whether or not the panel itself has exited.
static void StopChildGroup(PPChild *child) {
    dispatch_sync(StopQueue(), ^{
        if (!child || child.groupGone) return;
        StopGroup(child.pgid);
        if (GroupGone(child.pgid)) child.groupGone = YES;
    });
}

#pragma mark - Downloads, macOS 11.3 and later

API_AVAILABLE(macos(11.3))
@interface PPDownloads : NSObject <WKDownloadDelegate>
@property (weak) NSWindow *window;
@property (strong) NSMapTable<WKDownload *, NSArray<NSURL *> *> *replacing;  // download -> @[temporary, file]
@end

@implementation PPDownloads
- (instancetype)init {
    if ((self = [super init])) _replacing = [NSMapTable weakToStrongObjectsMapTable];
    return self;
}
- (void)download:(WKDownload *)download decideDestinationUsingResponse:(NSURLResponse *)response
        suggestedFilename:(NSString *)suggestedFilename completionHandler:(void (^)(NSURL *))completionHandler {
    AskWhereToSave(self.window, suggestedFilename, ^(NSURL *url) {
        // WKDownload refuses a destination that exists. The save panel has
        // already had the person confirm replacing it, so it goes to the
        // Trash. Where there is no Trash, a network volume say, the download
        // is saved beside it under another name and swapped in only once it
        // has finished, so the old file is never lost before the new one is
        // all there.
        if (url && [url checkResourceIsReachableAndReturnError:nil] &&
            ![[NSFileManager defaultManager] trashItemAtURL:url resultingItemURL:nil error:nil]) {
            NSString *name = [NSString stringWithFormat:@"%@ (downloading %@)", url.lastPathComponent,
                              [NSUUID UUID].UUIDString.lowercaseString];
            NSURL *temporary = [url.URLByDeletingLastPathComponent URLByAppendingPathComponent:name];
            [self.replacing setObject:@[temporary, url] forKey:download];
            url = temporary;
        }
        completionHandler(url);
    });
}
- (void)downloadDidFinish:(WKDownload *)download {
    NSArray<NSURL *> *swap = [self.replacing objectForKey:download];
    if (!swap) return;
    [self.replacing removeObjectForKey:download];
    NSError *err = nil;
    if (![[NSFileManager defaultManager] replaceItemAtURL:swap[1] withItemAtURL:swap[0] backupItemName:nil
                                                  options:0 resultingItemURL:nil error:&err])
        SayOnWindow(self.window, @"The download could not replace the file that was there.",
                    [NSString stringWithFormat:@"%@ It was saved beside it as “%@”.",
                     err.localizedDescription ?: @"", swap[0].lastPathComponent]);
}
- (void)download:(WKDownload *)download didFailWithError:(NSError *)error resumeData:(NSData *)resumeData {
    NSArray<NSURL *> *swap = [self.replacing objectForKey:download];
    if (swap) {  // only the part of the new download goes, the old file was never touched
        [self.replacing removeObjectForKey:download];
        [[NSFileManager defaultManager] removeItemAtURL:swap[0] error:nil];
    }
    SayOnWindow(self.window, @"The download did not finish.", error.localizedDescription);
}
@end

// WKUserContentController keeps its handlers alive, so the app is reached
// through this weak hop instead, which keeps the two from holding each other.
@interface PPWeakHandler : NSObject <WKScriptMessageHandler>
@property (weak) id<WKScriptMessageHandler> target;
@end
@implementation PPWeakHandler
- (void)userContentController:(WKUserContentController *)c didReceiveScriptMessage:(WKScriptMessage *)m {
    [self.target userContentController:c didReceiveScriptMessage:m];
}
@end

// For macOS 11.0 to 11.2 only: the page's <a download> clicks on its own blob:
// and same-origin links, read in the page and handed over as base64.
static NSString *const kSaveShim =
    @"(function(){window.addEventListener('click',function(e){"
     "var a=e.target&&e.target.closest?e.target.closest('a[download]'):null;"
     "if(!a||!(a.href.indexOf('blob:')===0||a.href.indexOf(location.origin+'/')===0))return;"
     "e.preventDefault();e.stopImmediatePropagation();var name=a.download||'download';"
     "fetch(a.href).then(function(r){return r.blob();}).then(function(b){return new Promise(function(ok,no){"
     "var f=new FileReader();f.onload=function(){ok(String(f.result));};f.onerror=function(){no(f.error);};"
     "f.readAsDataURL(b);});}).then(function(u){window.webkit.messageHandlers.ppSave.postMessage("
     "{name:name,data:u.slice(u.indexOf(',')+1)});});},true);})();";

#pragma mark - The application

@interface PPApp : NSObject <NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate,
                             WKScriptMessageHandler>
@property (copy) NSString *selfTest;         // nil, "ready" or "window"
@property (copy) NSString *resources, *gui, *python, *logPath, *pidPath;
@property int logFD, listenFD;               // listenFD, see "The port" above
@property BOOL ownsPidfile;                  // NO while another live launcher's is there
@property (strong) PPChild *child;
@property BOOL ready, stopping, reportedWindow;
@property int exitCode;
@property (strong) NSWindow *window;
@property (strong) WKWebView *webView;
@property (strong) id downloads;             // PPDownloads, on 11.3 and later
@property (strong) NSMutableArray *signalSources;
@end

@implementation PPApp

- (NSURL *)panelURL {
    return [NSURL URLWithString:[NSString stringWithFormat:@"http://127.0.0.1:%d/", self.child.port]];
}
- (BOOL)isPanelURL:(NSURL *)u {
    return self.child && [u.scheme isEqualToString:@"http"] && [u.host isEqualToString:@"127.0.0.1"] &&
           u.port.intValue == self.child.port;
}

- (void)log:(NSString *)fmt, ... NS_FORMAT_FUNCTION(1, 2) {
    va_list ap; va_start(ap, fmt);
    NSString *s = [[NSString alloc] initWithFormat:fmt arguments:ap];
    va_end(ap);
    if (self.logFD >= 0) dprintf(self.logFD, "[%s] launcher: %s\n", [NSDate date].description.UTF8String, s.UTF8String);
}

- (void)selfTestFailed:(NSString *)why {
    fprintf(stderr, "PaperPull launcher self-test failed: %s\n", why.UTF8String);
    self.exitCode = 1;
    [NSApp terminate:nil];
}

#pragma mark Start

// $HOME, as paperpull-panel.sh and the panel itself use it, so a test that
// points HOME elsewhere moves the log and pidfile along with the panel's data.
- (NSString *)home {
    const char *h = getenv("HOME");
    NSString *s = (h && h[0] == '/') ? @(h) : nil;  // nil too when it is not UTF-8
    return s ?: NSHomeDirectory();
}

- (void)applicationDidFinishLaunching:(NSNotification *)n {
    self.resources = [NSBundle mainBundle].resourcePath;
    self.gui = [self.resources stringByAppendingPathComponent:@"gui"];
    self.python = [self.resources stringByAppendingPathComponent:@"python/bin/python3"];
    NSString *home = [self home];
    NSString *logs = [home stringByAppendingPathComponent:@"Library/Logs/PaperPull"];
    NSString *support = [home stringByAppendingPathComponent:@"Library/Application Support/PaperPull"];
    for (NSString *d in @[logs, support])
        [[NSFileManager defaultManager] createDirectoryAtPath:d withIntermediateDirectories:YES attributes:nil error:nil];
    self.logPath = [logs stringByAppendingPathComponent:@"panel.log"];
    self.pidPath = [support stringByAppendingPathComponent:@"panel.pid"];
    struct stat st;
    BOOL big = stat(self.logPath.fileSystemRepresentation, &st) == 0 && st.st_size > kLogLimit;
    self.logFD = open(self.logPath.fileSystemRepresentation,
                      O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC | (big ? O_TRUNC : 0), 0644);
    [self watchSignals];

    if (self.selfTest) {
        __weak PPApp *weak = self;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(kSelfTestWithin * NSEC_PER_SEC)),
                       dispatch_get_main_queue(), ^{ [weak selfTestFailed:@"timed out after 60 seconds"]; });
    }
    if (!self.selfTest || [self.selfTest isEqualToString:@"window"]) {
        [self buildMenus];
        [self buildWindow];
    }
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:self.python]) {
        [self failedToStart:@"PaperPull is incomplete." info:[NSString stringWithFormat:
            @"%@ is missing. Download PaperPull again.", self.python]];
        return;
    }
    [self startPanel:YES];
}

// Off the main thread, since stopping a leftover panel can take seconds, and
// it has to be gone before its port can be listened on.
- (void)startPanel:(BOOL)first {
    __weak PPApp *weak = self;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        if (first) [weak stopLeftoverPanel];
        dispatch_async(dispatch_get_main_queue(), ^{ [weak startPanelOnSocket]; });
    });
}

- (void)watchSignals {
    self.signalSources = [NSMutableArray array];
    __weak PPApp *weak = self;
    int sigs[] = {SIGTERM, SIGINT, SIGHUP};
    signal(SIGPIPE, SIG_IGN);
    for (size_t i = 0; i < 3; i++) {
        signal(sigs[i], SIG_IGN);  // delivered to the source below instead
        dispatch_source_t s = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, (uintptr_t)sigs[i], 0,
                                                     dispatch_get_main_queue());
        dispatch_source_set_event_handler(s, ^{ if (!weak.stopping) [NSApp terminate:nil]; });
        dispatch_resume(s);
        [self.signalSources addObject:s];
    }
}

// Off the main thread. See "A panel left behind" above.
- (void)stopLeftoverPanel {
    self.ownsPidfile = YES;
    NSString *text = [NSString stringWithContentsOfFile:self.pidPath encoding:NSUTF8StringEncoding error:nil];
    NSArray<NSString *> *lines = [text componentsSeparatedByString:@"\n"];
    pid_t pid = (pid_t)lines.firstObject.intValue;
    pid_t owner = lines.count > 1 ? (pid_t)lines[1].intValue : 0;  // 0 in a pidfile of the old, one-line kind
    if (owner > 1 && owner != getpid() &&
        ProcessRuns(owner, [NSBundle mainBundle].executablePath.fileSystemRepresentation)) {
        [self log:@"leaving pid %d alone, the launcher that started it, pid %d, is still running", pid, owner];
        self.ownsPidfile = NO;
        return;
    }
    if (pid > 1 && pid != getpid() && ProcessHasArgument(pid, self.gui.fileSystemRepresentation)) {
        [self log:@"stopping the panel a previous launch left running, pid %d", pid];
        if (getpgid(pid) == pid) StopGroup(pid);  // always so, the launcher made it a group
        else kill(pid, SIGTERM);
    }
    unlink(self.pidPath.fileSystemRepresentation);
}

// Only when it still names this launcher, so a second copy of the app never
// takes away the first one's.
- (void)removePidfileIfOurs {
    if (!self.ownsPidfile || !self.pidPath) return;
    NSString *text = [NSString stringWithContentsOfFile:self.pidPath encoding:NSUTF8StringEncoding error:nil];
    NSArray<NSString *> *lines = [text componentsSeparatedByString:@"\n"];
    if (lines.count > 1 && lines[1].intValue == getpid()) unlink(self.pidPath.fileSystemRepresentation);
}

// PAPERPULL_PORT if it is set, else 8765, else any free port.
- (int)listenSocket {
    const char *env = getenv("PAPERPULL_PORT");
    if (env && atoi(env) > 0 && atoi(env) < 65536) return ListenOn(atoi(env));
    int s = ListenOn(kDefaultPort);
    return s >= 0 ? s : ListenOn(0);
}

- (void)startPanelOnSocket {
    if (self.stopping) return;
    if (self.listenFD < 0) self.listenFD = [self listenSocket];  // a restart keeps the one it has
    int port = self.listenFD >= 0 ? SocketPort(self.listenFD) : 0;
    if (port <= 0) { [self failedToStart:@"PaperPull could not find a free port." info:@""]; return; }
    char fdText[12]; snprintf(fdText, sizeof fdText, "%d", self.listenFD);
    const char *argv[] = {self.python.fileSystemRepresentation, "-m", "uvicorn", "app:app", "--fd", fdText,
                          "--app-dir", self.gui.fileSystemRepresentation, NULL};

    // The environment is the launcher's own plus the two settings
    // paperpull-panel.sh makes, kept as the bytes they are, since an entry
    // need not be UTF-8 and NSString would refuse it.
    const char *cache = [[self home] stringByAppendingPathComponent:@"Library/Caches/PaperPull/pycache"]
                            .fileSystemRepresentation;
    size_t count = 0;
    for (char **e = environ; *e; e++) count++;
    const char **envp = calloc(count + 3, sizeof(char *));
    size_t k = 0;
    for (char **e = environ; *e; e++)
        if (strncmp(*e, "PYTHONNOUSERSITE=", 17) && strncmp(*e, "PYTHONPYCACHEPREFIX=", 20)) envp[k++] = *e;
    char *prefix = NULL;
    if (asprintf(&prefix, "PYTHONPYCACHEPREFIX=%s", cache ?: "") < 0) prefix = NULL;
    envp[k++] = "PYTHONNOUSERSITE=1";
    if (prefix) envp[k++] = prefix;

    // Its own process group, nothing open but stdin from /dev/null, the log
    // and the listening socket, and default signal handling, since the
    // launcher ignores the signals it watches and an ignored signal would be
    // inherited.
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_addopen(&fa, 0, "/dev/null", O_RDONLY, 0);
    int out = self.logFD >= 0 ? self.logFD : open("/dev/null", O_WRONLY | O_CLOEXEC);
    posix_spawn_file_actions_adddup2(&fa, out, 1);
    posix_spawn_file_actions_adddup2(&fa, out, 2);
    posix_spawn_file_actions_addinherit_np(&fa, self.listenFD);  // exempt from CLOEXEC_DEFAULT, at its number
    posix_spawn_file_actions_addchdir_np(&fa, self.resources.fileSystemRepresentation);
    posix_spawnattr_t at;
    posix_spawnattr_init(&at);
    sigset_t none, dflt;
    sigemptyset(&none); sigemptyset(&dflt);
    sigaddset(&dflt, SIGTERM); sigaddset(&dflt, SIGINT); sigaddset(&dflt, SIGHUP); sigaddset(&dflt, SIGPIPE);
    posix_spawnattr_setsigmask(&at, &none);
    posix_spawnattr_setsigdefault(&at, &dflt);
    posix_spawnattr_setpgroup(&at, 0);
    posix_spawnattr_setflags(&at, POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_SETSIGMASK | POSIX_SPAWN_SETSIGDEF |
                                  POSIX_SPAWN_CLOEXEC_DEFAULT);
    pid_t pid = 0;
    int err = posix_spawn(&pid, argv[0], &fa, &at, (char *const *)argv, (char *const *)envp);
    posix_spawn_file_actions_destroy(&fa);
    posix_spawnattr_destroy(&at);
    free(envp);
    free(prefix);
    if (out != self.logFD) close(out);
    if (err) {
        [self failedToStart:@"PaperPull's control panel could not be started."
                       info:[NSString stringWithFormat:@"%s", strerror(err)]];
        return;
    }
    PPChild *child = [PPChild new];
    child.pid = pid; child.pgid = pid; child.port = port;  // setpgroup 0: a group of its own, numbered as it is
    self.child = child; self.ready = NO;
    if (self.ownsPidfile)
        [[NSString stringWithFormat:@"%d\n%d\n", pid, getpid()] writeToFile:self.pidPath atomically:YES
                                                                  encoding:NSUTF8StringEncoding error:nil];
    [self log:@"started the panel, pid %d, http://127.0.0.1:%d", pid, port];

    // The waiter. A thread of its own, since it sits in waitpid for as long
    // as the panel runs. Whatever the panel leaves behind in its group, runs
    // of a panel that died or a panel that exited cleanly alike, is stopped
    // with it.
    __weak PPApp *weak = self;
    [NSThread detachNewThreadWithBlock:^{
        int st = 0;
        while (waitpid(child.pid, &st, 0) < 0 && errno == EINTR) {}
        child.status = st; child.done = YES;
        StopChildGroup(child);
        dispatch_async(dispatch_get_main_queue(), ^{ [weak panelExited:child]; });
    }];
    [self waitUntilReady:child];
}

// The readiness poll. Every connection on the port reaches the panel or
// nobody, see "The port" above, but one is queued by the system before the
// panel accepts it, so only a real answer to GET / counts.
- (void)waitUntilReady:(PPChild *)child {
    __weak PPApp *weak = self;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        double deadline = Now() + kReadyWithin;
        while (Now() < deadline && !child.done) {
            if (HTTPStatus(child.port) == 200) {
                dispatch_async(dispatch_get_main_queue(), ^{ [weak panelReady:child]; });
                return;
            }
            usleep((useconds_t)(kPollEvery * 1e6));
        }
        if (!child.done) dispatch_async(dispatch_get_main_queue(), ^{ [weak panelNeverAnswered:child]; });
    });
}

- (void)panelReady:(PPChild *)child {
    if (child != self.child || self.stopping) return;
    self.ready = YES;
    if ([self.selfTest isEqualToString:@"ready"]) {
        printf("READY http://127.0.0.1:%d\n", child.port);
        fflush(stdout);
        [NSApp terminate:nil];
        return;
    }
    [self.webView loadRequest:[NSURLRequest requestWithURL:self.panelURL]];
}

- (void)panelNeverAnswered:(PPChild *)child {
    if (child != self.child || self.stopping) return;
    [self log:@"the panel did not answer within %.0f seconds", kReadyWithin];
    if (self.selfTest) {
        [self failedToStart:@"PaperPull's control panel did not start." info:@"It did not answer within 45 seconds."];
        return;
    }
    // It may only be slow, so waiting is offered as well, polling the same
    // panel for another 45 seconds. A panel that answers then is shown.
    __weak PPApp *weak = self;
    [self ask:@"PaperPull's control panel did not start."
         info:@"It has not answered within 45 seconds. It may only be slow, or the log may say why."
      buttons:@[@"Keep waiting", @"Quit"] then:^(NSInteger i) {
        if (i == 0) [weak waitUntilReady:child]; else [NSApp terminate:nil];
    }];
}

- (void)panelExited:(PPChild *)child {
    if (child != self.child || self.stopping) return;
    int st = child.status;
    [self removePidfileIfOurs];
    NSString *how = WIFEXITED(st) ? [NSString stringWithFormat:@"exited with status %d", WEXITSTATUS(st)]
                                  : [NSString stringWithFormat:@"was stopped by signal %d", WTERMSIG(st)];
    [self log:@"the panel %@", how];
    if (self.selfTest) { [self selfTestFailed:[@"the panel " stringByAppendingString:how]]; return; }
    if (WIFEXITED(st) && WEXITSTATUS(st) == 0) {  // stopped on purpose
        self.child = nil;
        [NSApp terminate:nil];
        return;
    }
    if (!self.ready) {
        [self failedToStart:@"PaperPull's control panel did not start."
                       info:[NSString stringWithFormat:@"It %@ before it was ready. The log may say why.", how]];
        return;
    }
    self.ready = NO;
    __weak PPApp *weak = self;
    [self ask:@"PaperPull's control panel stopped."
         info:[NSString stringWithFormat:@"It %@. Restarting it is safe, nothing already saved is lost.", how]
      buttons:@[@"Restart panel", @"Quit"] then:^(NSInteger i) {
        if (i == 0) [weak restartPanel]; else [NSApp terminate:nil];
    }];
}

- (void)restartPanel {
    [self showPlaceholder:@"Restarting PaperPull…"];
    [self startPanel:NO];  // the same socket and port, so the page keeps its storage
}

- (void)failedToStart:(NSString *)what info:(NSString *)info {
    if (self.selfTest) { [self selfTestFailed:[NSString stringWithFormat:@"%@ %@", what, info]]; return; }
    [self ask:what info:info buttons:@[@"Quit"] then:^(NSInteger i) { (void)i; [NSApp terminate:nil]; }];
}

// An alert as a sheet on the window, with Show Log always offered beside the
// given buttons. Show Log opens the log and asks again.
- (void)ask:(NSString *)what info:(NSString *)info buttons:(NSArray<NSString *> *)buttons
       then:(void (^)(NSInteger))then {
    NSAlert *a = [NSAlert new];
    a.messageText = what; a.informativeText = info;
    for (NSString *b in buttons) [a addButtonWithTitle:b];
    [a addButtonWithTitle:@"Show Log"];
    __weak PPApp *weak = self;
    void (^answer)(NSModalResponse) = ^(NSModalResponse r) {
        NSInteger i = r - NSAlertFirstButtonReturn;
        if (i == (NSInteger)buttons.count) { [weak showLog:nil]; [weak ask:what info:info buttons:buttons then:then]; }
        else then(i);
    };
    if (self.window) {
        [self.window makeKeyAndOrderFront:nil];
        [a beginSheetModalForWindow:self.window completionHandler:answer];
    } else answer([a runModal]);
}

#pragma mark Quit

// The panel's group is stopped off the main thread, then the app is let go.
// That is so whether the panel is still running or has already exited, and a
// stop the waiter has under way is waited for, see StopChildGroup. Nothing
// the panel started outlives this.
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)app {
    if (self.stopping) return NSTerminateLater;  // already on its way out, the reply is coming
    self.stopping = YES;
    PPChild *child = self.child;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        StopChildGroup(child);
        [self removePidfileIfOurs];
        // Not dispatch_async to the main queue: terminate: is often called
        // from a main-queue block, and AppKit waits for this reply inside
        // that block, where the queue cannot run another. The run loop can.
        CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, ^{
            [NSApp replyToApplicationShouldTerminate:YES];
        });
        CFRunLoopWakeUp(CFRunLoopGetMain());
    });
    return NSTerminateLater;
}

- (void)applicationWillTerminate:(NSNotification *)n {
    [self log:@"quit"];
    if (self.listenFD >= 0) close(self.listenFD);  // the panel is gone by now, see above
    self.listenFD = -1;
    fflush(stdout);
    if (self.exitCode) exit(self.exitCode);
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app { return YES; }
- (BOOL)applicationSupportsSecureRestorableState:(NSApplication *)app { return YES; }

#pragma mark Window and menus

- (void)showPlaceholder:(NSString *)text {
    NSString *html = [NSString stringWithFormat:
        @"<!doctype html><meta charset=utf-8><meta name=color-scheme content='light dark'>"
         "<body style='margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
         "font:15px -apple-system,system-ui;color:#888'>%@</body>", text];
    [self.webView loadHTMLString:html baseURL:nil];
}

- (void)buildWindow {
    WKWebViewConfiguration *cfg = [WKWebViewConfiguration new];
    // Both are off in WKWebView already. They are set anyway, through keys
    // WebKit does not publish, so a change of default could never let a
    // file: page read the disk. A WebKit without the keys is simply skipped.
    @try { [cfg.preferences setValue:@NO forKey:@"allowFileAccessFromFileURLs"]; } @catch (NSException *e) { (void)e; }
    @try { [cfg setValue:@NO forKey:@"allowUniversalAccessFromFileURLs"]; } @catch (NSException *e) { (void)e; }
    cfg.preferences.javaScriptCanOpenWindowsAutomatically = NO;
    if (@available(macOS 11.3, *)) {
        PPDownloads *d = [PPDownloads new];
        self.downloads = d;
    } else {
        PPWeakHandler *h = [PPWeakHandler new];
        h.target = self;
        [cfg.userContentController addScriptMessageHandler:h name:@"ppSave"];
        [cfg.userContentController addUserScript:[[WKUserScript alloc] initWithSource:kSaveShim
            injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:YES]];
    }
    NSRect frame = NSMakeRect(0, 0, 1180, 820);
    NSWindow *w = [[NSWindow alloc] initWithContentRect:frame
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable |
                  NSWindowStyleMaskResizable backing:NSBackingStoreBuffered defer:NO];
    w.title = @"PaperPull";
    w.releasedWhenClosed = NO;
    w.contentMinSize = NSMakeSize(820, 600);
    w.tabbingMode = NSWindowTabbingModeDisallowed;
    w.collectionBehavior = NSWindowCollectionBehaviorFullScreenPrimary;
    w.delegate = self;
    if (![w setFrameUsingName:@"PaperPull"]) [w center];
    w.frameAutosaveName = @"PaperPull";
    WKWebView *wv = [[WKWebView alloc] initWithFrame:frame configuration:cfg];
    wv.navigationDelegate = self;
    wv.UIDelegate = self;
    wv.allowsBackForwardNavigationGestures = NO;
    double zoom = [[NSUserDefaults standardUserDefaults] doubleForKey:@"PageZoom"];
    if (zoom >= 0.5 && zoom <= 3) wv.pageZoom = zoom;
    w.contentView = wv;
    self.window = w; self.webView = wv;
    if ([self.downloads respondsToSelector:@selector(setWindow:)]) [self.downloads setWindow:w];
    [self showPlaceholder:@"Starting PaperPull…"];
    if (self.selfTest) [w orderFront:nil];  // shown, but focus stays where it is
    else { [w makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES]; }
}

static NSMenuItem *Add(NSMenu *m, NSString *title, SEL action, NSString *key, NSEventModifierFlags mods, id target) {
    NSMenuItem *i = [m addItemWithTitle:title action:action keyEquivalent:key ?: @""];
    if (mods) i.keyEquivalentModifierMask = mods;
    i.target = target;
    return i;
}

static NSMenu *Submenu(NSMenu *bar, NSString *title) {
    NSMenuItem *top = [bar addItemWithTitle:title action:NULL keyEquivalent:@""];
    NSMenu *m = [[NSMenu alloc] initWithTitle:title];
    top.submenu = m;
    return m;
}

- (void)buildMenus {
    NSMenu *bar = [NSMenu new];
    NSEventModifierFlags cmd = NSEventModifierFlagCommand;
    NSMenu *app = Submenu(bar, @"PaperPull");
    Add(app, @"About PaperPull", @selector(showAbout:), nil, 0, self);
    [app addItem:[NSMenuItem separatorItem]];
    Add(app, @"Hide PaperPull", @selector(hide:), @"h", 0, NSApp);
    Add(app, @"Hide Others", @selector(hideOtherApplications:), @"h", cmd | NSEventModifierFlagOption, NSApp);
    Add(app, @"Show All", @selector(unhideAllApplications:), nil, 0, NSApp);
    [app addItem:[NSMenuItem separatorItem]];
    Add(app, @"Quit PaperPull", @selector(terminate:), @"q", 0, NSApp);

    // Edit items go to the first responder, the web view, so Cmd-C and
    // Cmd-V work in the page's fields.
    NSMenu *edit = Submenu(bar, @"Edit");
    Add(edit, @"Undo", @selector(undo:), @"z", 0, nil);
    Add(edit, @"Redo", @selector(redo:), @"z", cmd | NSEventModifierFlagShift, nil);
    [edit addItem:[NSMenuItem separatorItem]];
    Add(edit, @"Cut", @selector(cut:), @"x", 0, nil);
    Add(edit, @"Copy", @selector(copy:), @"c", 0, nil);
    Add(edit, @"Paste", @selector(paste:), @"v", 0, nil);
    Add(edit, @"Select All", @selector(selectAll:), @"a", 0, nil);

    NSMenu *view = Submenu(bar, @"View");
    Add(view, @"Reload", @selector(reloadPanel:), @"r", 0, self);
    [view addItem:[NSMenuItem separatorItem]];
    Add(view, @"Actual Size", @selector(zoomReset:), @"0", 0, self);
    Add(view, @"Zoom In", @selector(zoomIn:), @"+", 0, self);
    // Cmd-= as well, the same key without Shift, as browsers accept.
    NSMenuItem *eq = Add(view, @"Zoom In", @selector(zoomIn:), @"=", 0, self);
    eq.hidden = YES; eq.allowsKeyEquivalentWhenHidden = YES;
    Add(view, @"Zoom Out", @selector(zoomOut:), @"-", 0, self);
    [view addItem:[NSMenuItem separatorItem]];
    Add(view, @"Enter Full Screen", @selector(toggleFullScreen:), @"f", cmd | NSEventModifierFlagControl, nil);

    NSMenu *win = Submenu(bar, @"Window");
    Add(win, @"Minimize", @selector(performMiniaturize:), @"m", 0, nil);
    Add(win, @"Zoom", @selector(performZoom:), nil, 0, nil);
    Add(win, @"Close", @selector(performClose:), @"w", 0, nil);
    [win addItem:[NSMenuItem separatorItem]];
    Add(win, @"Bring All to Front", @selector(arrangeInFront:), nil, 0, NSApp);
    NSApp.windowsMenu = win;

    NSMenu *help = Submenu(bar, @"Help");
    Add(help, @"PaperPull Guide", @selector(openGuide:), nil, 0, self);
    Add(help, @"Show Panel Log", @selector(showLog:), nil, 0, self);
    NSApp.helpMenu = help;
    NSApp.mainMenu = bar;
}

- (void)showAbout:(id)sender {
    NSString *v = [NSBundle mainBundle].infoDictionary[@"CFBundleShortVersionString"] ?: @"";
    [NSApp orderFrontStandardAboutPanelWithOptions:@{NSAboutPanelOptionApplicationVersion: v,
                                                     NSAboutPanelOptionVersion: @""}];
    [NSApp activateIgnoringOtherApps:YES];
}
- (void)openGuide:(id)sender { [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:kGuideURL]]; }
- (void)showLog:(id)sender { [[NSWorkspace sharedWorkspace] openURL:[NSURL fileURLWithPath:self.logPath]]; }

// After a restart the web view may still show the starting page or a failed
// load, so Reload goes to the panel itself rather than reloading that.
- (void)reloadPanel:(id)sender {
    if (!self.ready) { NSBeep(); return; }
    if ([self isPanelURL:self.webView.URL]) [self.webView reload];
    else [self.webView loadRequest:[NSURLRequest requestWithURL:self.panelURL]];
}
- (void)setZoom:(double)z {
    self.webView.pageZoom = MAX(0.5, MIN(3.0, z));
    [[NSUserDefaults standardUserDefaults] setDouble:self.webView.pageZoom forKey:@"PageZoom"];
}
- (void)zoomReset:(id)sender { [self setZoom:1]; }
- (void)zoomIn:(id)sender { [self setZoom:self.webView.pageZoom * 1.1]; }
- (void)zoomOut:(id)sender { [self setZoom:self.webView.pageZoom / 1.1]; }

#pragma mark What the web view may show

// The default browser, for http, https and mailto only. Nothing else leaves.
- (void)openOutside:(NSURL *)u {
    NSString *s = u.scheme.lowercaseString;
    if ([s isEqualToString:@"http"] || [s isEqualToString:@"https"] || [s isEqualToString:@"mailto"])
        [[NSWorkspace sharedWorkspace] openURL:u];
}

- (BOOL)isOwnBlob:(NSURL *)u {
    return self.child && [u.absoluteString hasPrefix:[NSString stringWithFormat:@"blob:http://127.0.0.1:%d/", self.child.port]];
}

- (void)webView:(WKWebView *)wv decidePolicyForNavigationAction:(WKNavigationAction *)a
    decisionHandler:(void (^)(WKNavigationActionPolicy))decide {
    NSURL *u = a.request.URL;
    if (@available(macOS 11.3, *)) {
        if (a.shouldPerformDownload && ([self isPanelURL:u] || [self isOwnBlob:u])) {
            decide(WKNavigationActionPolicyDownload);
            return;
        }
    }
    BOOL blank = [u.absoluteString isEqualToString:@"about:blank"];
    BOOL own = [self isPanelURL:u] || blank;
    if (a.targetFrame == nil) {           // target=_blank, which createWebView also sees
        decide(WKNavigationActionPolicyCancel);
        [self openOutside:u];
    } else if (own) {
        decide(WKNavigationActionPolicyAllow);
    } else {
        decide(WKNavigationActionPolicyCancel);
        if (a.targetFrame.isMainFrame) [self openOutside:u];  // a frame's own loads just stop
    }
}

- (void)webView:(WKWebView *)wv decidePolicyForNavigationResponse:(WKNavigationResponse *)r
    decisionHandler:(void (^)(WKNavigationResponsePolicy))decide {
    NSHTTPURLResponse *h = [r.response isKindOfClass:[NSHTTPURLResponse class]] ? (NSHTTPURLResponse *)r.response : nil;
    NSString *disp = [h valueForHTTPHeaderField:@"Content-Disposition"].lowercaseString ?: @"";
    if (r.canShowMIMEType && ![disp hasPrefix:@"attachment"]) { decide(WKNavigationResponsePolicyAllow); return; }
    if (@available(macOS 11.3, *)) { decide(WKNavigationResponsePolicyDownload); return; }
    decide(WKNavigationResponsePolicyCancel);
    if (r.isForMainFrame) [self openOutside:r.response.URL];
}

- (void)webView:(WKWebView *)wv navigationAction:(WKNavigationAction *)a didBecomeDownload:(WKDownload *)d
    API_AVAILABLE(macos(11.3)) {
    d.delegate = self.downloads;
}
- (void)webView:(WKWebView *)wv navigationResponse:(WKNavigationResponse *)r didBecomeDownload:(WKDownload *)d
    API_AVAILABLE(macos(11.3)) {
    d.delegate = self.downloads;
}

- (void)webView:(WKWebView *)wv didFinishNavigation:(WKNavigation *)nav {
    if (![self.selfTest isEqualToString:@"window"] || self.reportedWindow || ![self isPanelURL:wv.URL]) return;
    self.reportedWindow = YES;
    __weak PPApp *weak = self;
    [wv evaluateJavaScript:@"document.title" completionHandler:^(id title, NSError *err) {
        if (err) { [weak selfTestFailed:[@"document.title: " stringByAppendingString:err.localizedDescription]]; return; }
        printf("WINDOW title=%s\n", [NSString stringWithFormat:@"%@", title ?: @""].UTF8String);
        fflush(stdout);
        [NSApp terminate:nil];
    }];
}

- (void)loadFailed:(WKWebView *)wv error:(NSError *)err {
    // Cancelled loads, and loads that became downloads, are not failures.
    if (err.code == NSURLErrorCancelled || ([err.domain isEqualToString:@"WebKitErrorDomain"] && err.code == 102)) return;
    if ([self.selfTest isEqualToString:@"window"]) { [self selfTestFailed:err.localizedDescription]; return; }
    if (self.ready && ![self isPanelURL:wv.URL])
        [self showPlaceholder:@"The control panel could not be reached. Choose View, Reload to try again."];
}
- (void)webView:(WKWebView *)wv didFailProvisionalNavigation:(WKNavigation *)n withError:(NSError *)e {
    [self loadFailed:wv error:e];
}
- (void)webView:(WKWebView *)wv didFailNavigation:(WKNavigation *)n withError:(NSError *)e {
    [self loadFailed:wv error:e];
}

// The page's own process died (WebKit restarts it); show the panel again.
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)wv {
    if (self.ready) [wv loadRequest:[NSURLRequest requestWithURL:self.panelURL]];
}

#pragma mark Panels the page asks for

- (WKWebView *)webView:(WKWebView *)wv createWebViewWithConfiguration:(WKWebViewConfiguration *)c
   forNavigationAction:(WKNavigationAction *)a windowFeatures:(WKWindowFeatures *)f {
    [self openOutside:a.request.URL];
    return nil;
}

- (void)webView:(WKWebView *)wv runOpenPanelWithParameters:(WKOpenPanelParameters *)p
    initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSArray<NSURL *> *))done {
    NSOpenPanel *o = [NSOpenPanel openPanel];
    o.allowsMultipleSelection = p.allowsMultipleSelection;
    o.canChooseDirectories = p.allowsDirectories;
    o.canChooseFiles = YES;
    [o beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse r) {
        done(r == NSModalResponseOK ? o.URLs : nil);
    }];
}

// alert, confirm and prompt, as sheets titled PaperPull rather than with the
// page's address.
- (NSAlert *)pageAlert:(NSString *)message buttons:(NSArray *)buttons {
    NSAlert *a = [NSAlert new];
    a.messageText = @"PaperPull";
    a.informativeText = message ?: @"";
    for (NSString *b in buttons) [a addButtonWithTitle:b];
    return a;
}
- (void)webView:(WKWebView *)wv runJavaScriptAlertPanelWithMessage:(NSString *)m
    initiatedByFrame:(WKFrameInfo *)f completionHandler:(void (^)(void))done {
    [[self pageAlert:m buttons:@[@"OK"]] beginSheetModalForWindow:self.window
                                                completionHandler:^(NSModalResponse r) { (void)r; done(); }];
}
- (void)webView:(WKWebView *)wv runJavaScriptConfirmPanelWithMessage:(NSString *)m
    initiatedByFrame:(WKFrameInfo *)f completionHandler:(void (^)(BOOL))done {
    [[self pageAlert:m buttons:@[@"OK", @"Cancel"]] beginSheetModalForWindow:self.window
        completionHandler:^(NSModalResponse r) { done(r == NSAlertFirstButtonReturn); }];
}
- (void)webView:(WKWebView *)wv runJavaScriptTextInputPanelWithPrompt:(NSString *)m defaultText:(NSString *)text
    initiatedByFrame:(WKFrameInfo *)f completionHandler:(void (^)(NSString *))done {
    NSAlert *a = [self pageAlert:m buttons:@[@"OK", @"Cancel"]];
    NSTextField *field = [NSTextField textFieldWithString:text ?: @""];
    field.frame = NSMakeRect(0, 0, 300, 24);
    a.accessoryView = field;
    a.window.initialFirstResponder = field;
    [a beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse r) {
        done(r == NSAlertFirstButtonReturn ? field.stringValue : nil);
    }];
}

// macOS 11.0 to 11.2: a download the page read itself, see kSaveShim.
- (void)userContentController:(WKUserContentController *)c didReceiveScriptMessage:(WKScriptMessage *)m {
    NSDictionary *d = [m.body isKindOfClass:[NSDictionary class]] ? m.body : nil;
    NSData *data = [d[@"data"] isKindOfClass:[NSString class]]
        ? [[NSData alloc] initWithBase64EncodedString:d[@"data"] options:0] : nil;
    NSString *name = [d[@"name"] isKindOfClass:[NSString class]] ? d[@"name"] : @"download";
    if (!data || ![self isPanelURL:m.frameInfo.request.URL]) return;
    NSWindow *w = self.window;
    AskWhereToSave(w, name, ^(NSURL *url) {
        NSError *err = nil;
        if (url && ![data writeToURL:url options:NSDataWritingAtomic error:&err])
            SayOnWindow(w, @"The download could not be saved.", err.localizedDescription);
    });
}

@end

int main(void) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        PPApp *delegate = [PPApp new];
        delegate.logFD = -1;
        delegate.listenFD = -1;
        const char *mode = getenv("PAPERPULL_LAUNCHER_SELFTEST");
        if (mode && *mode) {
            if (strcmp(mode, "ready") && strcmp(mode, "window")) {
                fprintf(stderr, "PAPERPULL_LAUNCHER_SELFTEST must be ready or window, not %s\n", mode);
                return 1;
            }
            delegate.selfTest = @(mode);
        }
        // The ready test has no window, so no Dock icon either.
        app.activationPolicy = [delegate.selfTest isEqualToString:@"ready"]
            ? NSApplicationActivationPolicyProhibited : NSApplicationActivationPolicyRegular;
        app.delegate = delegate;
        [app run];
    }
    return 0;
}
