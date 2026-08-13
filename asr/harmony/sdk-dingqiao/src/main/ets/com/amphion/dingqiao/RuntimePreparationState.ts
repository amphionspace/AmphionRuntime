export class RuntimePreparationSnapshot {
  readonly runtimeGeneration: number;
  readonly modelGeneration: number;

  constructor(runtimeGeneration: number, modelGeneration: number) {
    this.runtimeGeneration = runtimeGeneration;
    this.modelGeneration = modelGeneration;
  }
}

export class RuntimePreparationState {
  private runtimeGeneration: number = 0;
  private modelGeneration: number = 0;
  private defaultModelPrepared: boolean = false;
  private task?: Promise<void>;

  snapshot(): RuntimePreparationSnapshot {
    return new RuntimePreparationSnapshot(this.runtimeGeneration, this.modelGeneration);
  }

  activeTask(): Promise<void> | undefined {
    return this.task;
  }

  publishTask(task: Promise<void>): void {
    this.task = task;
  }

  clearTask(task: Promise<void>): void {
    if (this.task === task) this.task = undefined;
  }

  isRuntimeCurrent(snapshot: RuntimePreparationSnapshot): boolean {
    return snapshot.runtimeGeneration === this.runtimeGeneration;
  }

  isModelCurrent(snapshot: RuntimePreparationSnapshot): boolean {
    return snapshot.modelGeneration === this.modelGeneration;
  }

  isCurrent(snapshot: RuntimePreparationSnapshot): boolean {
    return this.isRuntimeCurrent(snapshot) && this.isModelCurrent(snapshot);
  }

  isDefaultModelPrepared(): boolean {
    return this.defaultModelPrepared;
  }

  markPrepared(snapshot: RuntimePreparationSnapshot): boolean {
    if (!this.isCurrent(snapshot)) return false;
    this.defaultModelPrepared = true;
    return true;
  }

  markPrepareFailed(snapshot: RuntimePreparationSnapshot): boolean {
    if (!this.isCurrent(snapshot)) return false;
    this.defaultModelPrepared = false;
    return true;
  }

  invalidateModel(): void {
    this.modelGeneration += 1;
    this.defaultModelPrepared = false;
    this.task = undefined;
  }

  invalidateRuntime(): void {
    this.runtimeGeneration += 1;
    this.modelGeneration += 1;
    this.defaultModelPrepared = false;
    this.task = undefined;
  }
}
