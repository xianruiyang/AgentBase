class JavaWorker {
    int value = 1;

    int execute(int amount) {
        return amount + value;
    }
}

class Sample {
    static int javaWrapper() {
        return new JavaWorker().execute(1);
    }
}
