export type OrganizationId = number;

export type LoadableState<T> =
  | { status: "idle"; data?: undefined; error?: undefined }
  | { status: "loading"; data?: T; error?: undefined }
  | { status: "empty"; data?: undefined; error?: undefined }
  | { status: "success"; data: T; error?: undefined }
  | { status: "forbidden"; data?: undefined; error: Error }
  | { status: "conflict"; data?: T; error: Error }
  | { status: "error"; data?: T; error: Error };
