import type { SVGProps } from "react";

export type IconId =
  | "i-bell"
  | "i-book"
  | "i-chevron-down"
  | "i-chevron-left"
  | "i-chevron-right"
  | "i-grid"
  | "i-home"
  | "i-message"
  | "i-search"
  | "i-settings"
  | "i-user";

export type IconProps = Omit<SVGProps<SVGSVGElement>, "children"> & {
  id: IconId;
};

export function Icon({ className, id, ...props }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={["icon", className].filter(Boolean).join(" ")}
      {...props}
    >
      <use href={`#${id}`} />
    </svg>
  );
}
