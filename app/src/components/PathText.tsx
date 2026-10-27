import { Fragment } from "react";

/** A path that wraps only after its slashes, never inside a name, even at its hyphens. */
export function PathText({ path }: { path: string }) {
  const parts = path.split("/");
  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={index}>
          <span className="whitespace-nowrap">
            {part}
            {index < parts.length - 1 && "/"}
          </span>
          {index < parts.length - 1 && <wbr />}
        </Fragment>
      ))}
    </>
  );
}
