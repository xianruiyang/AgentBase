export function leafCall(): number {
  return 1;
}
export function middleCall(): number {
  return leafCall();
}
export function rootCall(): number {
  return middleCall();
}
export class BaseType {}
export class MiddleType extends BaseType {}
export class LeafType extends MiddleType {}
