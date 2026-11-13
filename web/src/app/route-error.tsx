import { isRouteErrorResponse, useRouteError } from "react-router";

import { ErrorState } from "@/components/app/common";

export function RouteError() {
  const err = useRouteError();
  const error = isRouteErrorResponse(err) ? new Error(`${err.status} ${err.statusText}`) : err;
  return (
    <div className="mx-auto max-w-xl p-8">
      <ErrorState error={error} onRetry={() => window.location.reload()} />
    </div>
  );
}
