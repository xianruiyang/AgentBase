struct Alpha {}
struct Beta {}
struct Holder { child: Alpha }

impl Alpha {
    fn ping(&self) {}
    fn new() -> Alpha { Alpha }

    fn exercise(&self, explicit: Alpha, borrowed: &Alpha, opaque: &dyn Runner) {
        explicit.ping();
        borrowed.ping();
        let local: Alpha = Alpha;
        local.ping();
        let made = Alpha {};
        made.ping();
        let built = Alpha::new();
        built.ping();
        self.ping();
        Alpha::ping(self);
        opaque.run();
    }
}

impl Beta {
    fn ping(&self) {}
}

impl Holder {
    fn field_call(&self) { self.child.ping(); }
}

trait Runner { fn run(&self); }

fn free_root(explicit: Alpha, opaque: &dyn Runner) {
    explicit.ping();
    let made = Alpha {};
    made.ping();
    opaque.run();
}

fn closure_value() {
    let ping = || {};
    ping();
}
