/* PaperPull.app's main executable: the window the control panel is shown in.

Compiled on the build machine by packaging/build_macos.py rather than being a
script, because notarization requires a Mach-O main executable carrying the
hardened runtime.

Only the window is here. gui/mac_host.py chooses the port, runs the panel, keeps
its log and stops it. This program starts that with the bundled Python, shows
the panel once it says READY, and closes its stdin to stop it.

The web view shows only the panel. Anything else goes to the default browser,
and only when it is http, https or mailto, so nothing the page links to can
turn the panel's own window into somebody else's page.

PAPERPULL_LAUNCHER_SELFTEST=ready starts the panel, prints "READY
http://127.0.0.1:<port>", stops it and exits 0. =window does the same through
the real window without taking focus, and prints "WINDOW title=<title>". Either
exits 1 with the reason on stderr, on any failure or after 60 seconds.
*/
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

static NSString *const kGuideURL = @"https://paperpull.net/guide.html";

// Not dispatch_async: terminate: is often called from a main-queue block, and
// AppKit waits for the reply inside that block, where the queue cannot run
// another. The run loop can.
static void OnMain(dispatch_block_t work) {
    CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, work);
    CFRunLoopWakeUp(CFRunLoopGetMain());
}

@interface PPApp : NSObject <NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate>
@property (copy) NSString *selfTest, *logPath;
@property (strong) NSTask *host;
@property (strong) NSFileHandle *hostInput;
@property (strong) NSWindow *window;
@property (strong) WKWebView *web;
@property int port, exitCode;
@property BOOL quitting;
@end

@implementation PPApp

#pragma mark The panel

- (void)startHost {
    NSString *res = NSBundle.mainBundle.resourcePath;
    NSTask *task = [NSTask new];
    task.executableURL = [NSURL fileURLWithPath:[res stringByAppendingPathComponent:@"python/bin/python3"]];
    // -B and -s: no bytecode written into the signed bundle, no user site.
    task.arguments = @[@"-B", @"-s", [res stringByAppendingPathComponent:@"gui/mac_host.py"]];
    NSPipe *input = [NSPipe pipe], *output = [NSPipe pipe];
    task.standardInput = input;
    task.standardOutput = output;
    __weak PPApp *weak = self;
    output.fileHandleForReading.readabilityHandler = ^(NSFileHandle *h) {
        NSData *data = h.availableData;
        if (!data.length) { h.readabilityHandler = nil; return; }
        NSString *line = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
        int port = 0;
        if (sscanf(line.UTF8String ?: "", "READY %d", &port) == 1) OnMain(^{ [weak panelReady:port]; });
    };
    task.terminationHandler = ^(NSTask *ended) { OnMain(^{ [weak hostEnded:ended]; }); };
    NSError *err = nil;
    if (![task launchAndReturnError:&err]) { [self panelFailed:err.localizedDescription]; return; }
    self.host = task;
    self.hostInput = input.fileHandleForWriting;
}

- (void)panelReady:(int)port {
    self.port = port;
    if ([self.selfTest isEqualToString:@"ready"]) {
        printf("READY http://127.0.0.1:%d\n", port);
        [NSApp terminate:nil];
    } else {
        [self showPanel];
    }
}

- (void)hostEnded:(NSTask *)ended {
    if (ended != self.host) return;
    if (self.quitting) { [NSApp replyToApplicationShouldTerminate:YES]; return; }
    if (ended.terminationStatus == 0 && !self.selfTest) { [NSApp terminate:nil]; return; }  // stopped on purpose
    [self panelFailed:@"The log may say why. Restarting it is safe, nothing already saved is lost."];
}

- (void)panelFailed:(NSString *)info {
    self.port = 0;
    if (self.selfTest) { [self selfTestFailed:info]; return; }
    NSAlert *a = [NSAlert new];
    a.messageText = @"PaperPull's control panel stopped.";
    a.informativeText = info;
    for (NSString *b in @[@"Restart", @"Quit", @"Show Log"]) [a addButtonWithTitle:b];
    __weak PPApp *weak = self;
    [self.window makeKeyAndOrderFront:nil];
    [a beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse r) {
        if (r == NSAlertFirstButtonReturn) { [weak showMessage:@"Restarting PaperPull…"]; [weak startHost]; }
        else if (r == NSAlertSecondButtonReturn) [NSApp terminate:nil];
        else { [weak showLog:nil]; [weak panelFailed:info]; }
    }];
}

- (void)selfTestFailed:(NSString *)why {
    fprintf(stderr, "PaperPull launcher self-test failed: %s\n", why.UTF8String);
    self.exitCode = 1;
    [NSApp terminate:nil];
}

#pragma mark Start and quit

- (void)applicationDidFinishLaunching:(NSNotification *)n {
    self.logPath = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/PaperPull/panel.log"];
    if (self.selfTest) {
        __weak PPApp *weak = self;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 60 * NSEC_PER_SEC), dispatch_get_main_queue(),
                       ^{ [weak selfTestFailed:@"timed out after 60 seconds"]; });
    }
    if (![self.selfTest isEqualToString:@"ready"]) { [self buildMenus]; [self buildWindow]; }
    [self startHost];
}

// Closing the host's stdin stops the panel and everything it started. The host
// ends once they are gone, and that is the reply, or 10 seconds if it never is.
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)app {
    if (!self.host.running) return NSTerminateNow;
    if (self.quitting) return NSTerminateLater;
    self.quitting = YES;
    [self.hostInput closeFile];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC), dispatch_get_global_queue(0, 0), ^{
        OnMain(^{ [NSApp replyToApplicationShouldTerminate:YES]; });
    });
    return NSTerminateLater;
}

- (void)applicationWillTerminate:(NSNotification *)n {
    fflush(stdout);
    if (self.exitCode) exit(self.exitCode);
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app { return YES; }
- (BOOL)applicationSupportsSecureRestorableState:(NSApplication *)app { return YES; }

#pragma mark Window and menus

- (NSURL *)panelURL { return [NSURL URLWithString:[NSString stringWithFormat:@"http://127.0.0.1:%d/", self.port]]; }
- (BOOL)isPanel:(NSURL *)u {
    return self.port && [u.scheme isEqualToString:@"http"] && [u.host isEqualToString:@"127.0.0.1"] &&
           u.port.intValue == self.port;
}
- (void)showPanel { [self.web loadRequest:[NSURLRequest requestWithURL:self.panelURL]]; }

- (void)showMessage:(NSString *)text {
    [self.web loadHTMLString:[NSString stringWithFormat:
        @"<!doctype html><meta charset=utf-8><meta name=color-scheme content='light dark'>"
         "<body style='margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
         "font:15px -apple-system,system-ui;color:#888'>%@</body>", text] baseURL:nil];
}

- (void)buildWindow {
    NSRect frame = NSMakeRect(0, 0, 1180, 820);
    NSWindow *w = [[NSWindow alloc] initWithContentRect:frame
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable |
                  NSWindowStyleMaskResizable backing:NSBackingStoreBuffered defer:NO];
    w.title = @"PaperPull";
    w.releasedWhenClosed = NO;
    w.contentMinSize = NSMakeSize(820, 600);
    w.tabbingMode = NSWindowTabbingModeDisallowed;
    if (![w setFrameUsingName:@"PaperPull"]) [w center];
    w.frameAutosaveName = @"PaperPull";
    WKWebView *web = [[WKWebView alloc] initWithFrame:frame configuration:[WKWebViewConfiguration new]];
    web.navigationDelegate = self;
    web.UIDelegate = self;
    w.contentView = web;
    self.window = w;
    self.web = web;
    [self showMessage:@"Starting PaperPull…"];
    if (self.selfTest) [w orderFront:nil];  // shown, but focus stays where it is
    else { [w makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES]; }
}

static void Add(NSMenu *m, NSString *title, SEL action, NSString *key, id target) {
    [m addItemWithTitle:title action:action keyEquivalent:key].target = target;
}

static NSMenu *Submenu(NSMenu *bar, NSString *title) {
    NSMenu *m = [[NSMenu alloc] initWithTitle:title];
    [bar addItemWithTitle:title action:NULL keyEquivalent:@""].submenu = m;
    return m;
}

- (void)buildMenus {
    NSMenu *bar = [NSMenu new];
    NSMenu *app = Submenu(bar, @"PaperPull");
    Add(app, @"About PaperPull", @selector(orderFrontStandardAboutPanel:), @"", NSApp);
    Add(app, @"Hide PaperPull", @selector(hide:), @"h", NSApp);
    Add(app, @"Quit PaperPull", @selector(terminate:), @"q", NSApp);

    // A nil target is the first responder, the web view, so Cmd-C and Cmd-V
    // work in the page's fields.
    NSMenu *edit = Submenu(bar, @"Edit");
    Add(edit, @"Undo", @selector(undo:), @"z", nil);
    Add(edit, @"Redo", @selector(redo:), @"Z", nil);
    Add(edit, @"Cut", @selector(cut:), @"x", nil);
    Add(edit, @"Copy", @selector(copy:), @"c", nil);
    Add(edit, @"Paste", @selector(paste:), @"v", nil);
    Add(edit, @"Select All", @selector(selectAll:), @"a", nil);

    NSMenu *view = Submenu(bar, @"View");
    Add(view, @"Reload", @selector(reload:), @"r", self);
    Add(view, @"Actual Size", @selector(zoomReset:), @"0", self);
    Add(view, @"Zoom In", @selector(zoomIn:), @"=", self);
    Add(view, @"Zoom Out", @selector(zoomOut:), @"-", self);

    NSMenu *win = Submenu(bar, @"Window");
    Add(win, @"Minimize", @selector(performMiniaturize:), @"m", nil);
    Add(win, @"Close", @selector(performClose:), @"w", nil);
    NSApp.windowsMenu = win;

    NSMenu *help = Submenu(bar, @"Help");
    Add(help, @"PaperPull Guide", @selector(openGuide:), @"", self);
    Add(help, @"Show Panel Log", @selector(showLog:), @"", self);
    NSApp.helpMenu = help;
    NSApp.mainMenu = bar;
}

- (void)openGuide:(id)sender { [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:kGuideURL]]; }
- (void)showLog:(id)sender { [NSWorkspace.sharedWorkspace openURL:[NSURL fileURLWithPath:self.logPath]]; }
- (void)reload:(id)sender { if (self.port) [self showPanel]; else NSBeep(); }
- (void)zoomReset:(id)sender { self.web.pageZoom = 1; }
- (void)zoomIn:(id)sender { self.web.pageZoom = MIN(3.0, self.web.pageZoom * 1.1); }
- (void)zoomOut:(id)sender { self.web.pageZoom = MAX(0.5, self.web.pageZoom / 1.1); }

#pragma mark What the web view may show

- (void)openOutside:(NSURL *)u {
    if ([@[@"http", @"https", @"mailto"] containsObject:u.scheme.lowercaseString ?: @""])
        [NSWorkspace.sharedWorkspace openURL:u];
}

- (void)webView:(WKWebView *)wv decidePolicyForNavigationAction:(WKNavigationAction *)a
    decisionHandler:(void (^)(WKNavigationActionPolicy))decide {
    NSURL *u = a.request.URL;
    NSString *ownBlob = [NSString stringWithFormat:@"blob:http://127.0.0.1:%d/", self.port];
    if (a.shouldPerformDownload && ([self isPanel:u] || [u.absoluteString hasPrefix:ownBlob])) {
        decide(WKNavigationActionPolicyDownload);
    } else if (a.targetFrame && ([self isPanel:u] || [u.absoluteString isEqualToString:@"about:blank"])) {
        decide(WKNavigationActionPolicyAllow);
    } else {
        decide(WKNavigationActionPolicyCancel);
        if (!a.targetFrame || a.targetFrame.isMainFrame) [self openOutside:u];  // a frame's own loads just stop
    }
}

- (void)webView:(WKWebView *)wv decidePolicyForNavigationResponse:(WKNavigationResponse *)r
    decisionHandler:(void (^)(WKNavigationResponsePolicy))decide {
    NSString *disposition = [r.response isKindOfClass:NSHTTPURLResponse.class]
        ? [(NSHTTPURLResponse *)r.response valueForHTTPHeaderField:@"Content-Disposition"].lowercaseString : nil;
    decide(r.canShowMIMEType && ![disposition hasPrefix:@"attachment"] ? WKNavigationResponsePolicyAllow
                                                                       : WKNavigationResponsePolicyDownload);
}

- (WKWebView *)webView:(WKWebView *)wv createWebViewWithConfiguration:(WKWebViewConfiguration *)c
   forNavigationAction:(WKNavigationAction *)a windowFeatures:(WKWindowFeatures *)f {
    [self openOutside:a.request.URL];
    return nil;
}

- (void)webView:(WKWebView *)wv didFinishNavigation:(WKNavigation *)nav {
    if (![self.selfTest isEqualToString:@"window"] || ![self isPanel:wv.URL]) return;
    [wv evaluateJavaScript:@"document.title" completionHandler:^(id title, NSError *err) {
        printf("WINDOW title=%s\n", [NSString stringWithFormat:@"%@", title ?: @""].UTF8String);
        [NSApp terminate:nil];
    }];
}

- (void)webView:(WKWebView *)wv didFailProvisionalNavigation:(WKNavigation *)n withError:(NSError *)e {
    if (e.code == NSURLErrorCancelled || e.code == 102) return;  // 102 is a load that became a download
    if (self.selfTest) [self selfTestFailed:e.localizedDescription];
    else [self showMessage:@"The control panel could not be reached. Choose View, Reload to try again."];
}

- (void)webViewWebContentProcessDidTerminate:(WKWebView *)wv { if (self.port) [self showPanel]; }

#pragma mark Files

- (void)webView:(WKWebView *)wv runOpenPanelWithParameters:(WKOpenPanelParameters *)p
    initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSArray<NSURL *> *))done {
    NSOpenPanel *o = [NSOpenPanel openPanel];
    o.allowsMultipleSelection = p.allowsMultipleSelection;
    [o beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse r) {
        done(r == NSModalResponseOK ? o.URLs : nil);
    }];
}

- (void)webView:(WKWebView *)wv navigationAction:(WKNavigationAction *)a didBecomeDownload:(WKDownload *)d { d.delegate = self; }
- (void)webView:(WKWebView *)wv navigationResponse:(WKNavigationResponse *)r didBecomeDownload:(WKDownload *)d { d.delegate = self; }

- (void)download:(WKDownload *)download decideDestinationUsingResponse:(NSURLResponse *)response
        suggestedFilename:(NSString *)name completionHandler:(void (^)(NSURL *))done {
    NSSavePanel *panel = [NSSavePanel savePanel];
    panel.nameFieldStringValue = name;
    panel.directoryURL = [NSFileManager.defaultManager URLsForDirectory:NSDownloadsDirectory
                                                              inDomains:NSUserDomainMask].firstObject;
    [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse r) {
        // WKDownload refuses a file that exists, and the panel has already
        // had the person agree to replace it, so the old one goes to the Trash.
        if (r == NSModalResponseOK) [NSFileManager.defaultManager trashItemAtURL:panel.URL resultingItemURL:nil error:nil];
        done(r == NSModalResponseOK ? panel.URL : nil);
    }];
}

- (void)download:(WKDownload *)download didFailWithError:(NSError *)error resumeData:(NSData *)data {
    NSAlert *a = [NSAlert new];
    a.messageText = @"The download did not finish.";
    a.informativeText = error.localizedDescription;
    [a beginSheetModalForWindow:self.window completionHandler:nil];
}

@end

int main(void) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        PPApp *delegate = [PPApp new];
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
