class JavaScriptWorker {
    execute(amount) {
        return amount;
    }
}

function javaScriptWrapper() {
    return new JavaScriptWorker().execute(1);
}
