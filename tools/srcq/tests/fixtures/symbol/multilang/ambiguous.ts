class LeftWorker {
    execute(): number {
        return 1;
    }
}

class RightWorker {
    execute(): number {
        return 2;
    }
}

export function callLeft(worker: LeftWorker): number {
    return worker.execute();
}
