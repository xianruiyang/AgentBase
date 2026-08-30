struct RustWorker {
    value: i32,
}

impl RustWorker {
    fn execute(&self, amount: i32) -> i32 {
        amount + self.value
    }
}

fn rust_wrapper() -> i32 {
    RustWorker { value: 1 }.execute(1)
}
