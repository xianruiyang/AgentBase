import { Widget } from './widget.js';
export const dirtyValue: number = 1;
export const dirtyWidget = new Widget();
export function dirtyLeaf(): number { return 1; }
export function dirtyRoot(): number { return dirtyLeaf(); }
export class DirtyBase {}
export class DirtyMiddle extends DirtyBase {}
export class DirtyLeaf extends DirtyMiddle {}
