// d3-force-3d ships no types. This declares only what the 3D graph lens uses, as small interfaces
// instead of `any`, so a misuse still fails the type check.
declare module 'd3-force-3d' {
  export interface Force {
    strength(value: number): Force
    distance(fn: (link: unknown) => number): Force
    links(links: unknown[]): Force
    id(fn: (node: { id: string }) => string): Force
  }
  export interface Simulation {
    nodes(nodes: unknown[]): Simulation
    force(name: string): Force | undefined
    force(name: string, force: Force | null): Simulation
    alpha(value: number): Simulation
    alphaMin(): number
    alphaDecay(value: number): Simulation
    velocityDecay(value: number): Simulation
    tick(iterations?: number): Simulation
    stop(): Simulation
    // read with no argument
    alpha(): number
  }
  export function forceSimulation(nodes?: unknown[], numDimensions?: number): Simulation
  export function forceLink(links?: unknown[]): Force
  export function forceManyBody(): Force
  export function forceX(x?: number): Force
  export function forceY(y?: number): Force
  export function forceZ(z?: number): Force
}
