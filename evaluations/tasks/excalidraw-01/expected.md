# Expected finding

An arrow bound to a shape ends in a different place when it is first drawn than after a bound shape is dragged.

- Drawn: the arrow end stays where the user releases it, just outside the shape's edge.
- After dragging the shape, or the shape at the arrow's other end: the end snaps to about 20px inside the shape's edge.

It applies to every bindable shape: rectangles, ellipses, diamonds, and text. Elbow arrows are not affected.

Cause: `profile/scenario.patch` changes `updateBoundPoint` in `packages/excalidraw/element/binding.ts`, which places a bound end again when a shape moves. Upstream places it at the edge plus the binding gap; the patch moves it a further `gap + 20` along the arrow, into the shape.
