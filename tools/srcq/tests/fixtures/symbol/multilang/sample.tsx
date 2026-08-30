class TsxWorker {
    execute(amount: number): number {
        return amount;
    }
}

function tsxWrapper(): number {
    return new TsxWorker().execute(1);
}
