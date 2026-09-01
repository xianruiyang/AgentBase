class PrimaryWorker {
    execute(): number { return 1; }
    static create(): number { return 3; }
}
class AlternateWorker { execute(): number { return 2; } }
class Owner {
    field: PrimaryWorker = new PrimaryWorker();
    readonly #privateField: PrimaryWorker = new PrimaryWorker();
    execute(): number { return 4; }
    run(parameter: PrimaryWorker): number {
        const explicit: PrimaryWorker = parameter;
        const initialized = new PrimaryWorker();
        let scoped: PrimaryWorker | AlternateWorker;
        { const scoped: AlternateWorker = new AlternateWorker(); scoped.execute(); }
        scoped = parameter;
        scoped.execute();
        const conflict: PrimaryWorker | AlternateWorker = parameter;
        return parameter.execute() + explicit.execute() + initialized.execute()
            + this.field.execute() + this.execute() + PrimaryWorker.create() + conflict.execute();
    }
    async #privateCaller(): Promise<number> { return this.#privateField.execute(); }
}
const arrowCaller = (worker: PrimaryWorker): number => worker.execute();
