class TypeScriptWorker {
    value = 1;

    execute(amount: number): number {
        return amount + this.value;
    }
}

function typeScriptWrapper(): number {
    return new TypeScriptWorker().execute(1);
}
