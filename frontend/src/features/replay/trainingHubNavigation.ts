import { t } from "../../i18n/index.js";
import { ReplayV2ApiError } from "./replayV2Api.js";
import type { TrainingRunReturnResponse } from "./replayV2Types.js";

export interface ReturnToHubApi {
  returnToHub(runId: string, signal?: AbortSignal): Promise<TrainingRunReturnResponse>;
}

export async function returnToTrainingHub(
  runId: string,
  api: ReturnToHubApi,
  navigate: (url: string) => void = (url) => window.location.assign(url),
  signal?: AbortSignal,
): Promise<TrainingRunReturnResponse> {
  let result: TrainingRunReturnResponse;
  for (let attempt = 0; ; attempt += 1) {
    signal?.throwIfAborted();
    try {
      result = await api.returnToHub(runId, signal);
      break;
    } catch (error) {
      // A just-opened progressive adapter may still hold a read lease. Keep
      // waiting for the server's durable release, without bypassing its fence.
      if (!(error instanceof ReplayV2ApiError)
        || error.code !== "TRAINING_RUN_BUSY"
        || error.details.reason !== "REVISION_CONFLICT"
        || attempt >= 19) throw error;
      await new Promise<void>((resolve) => setTimeout(resolve, 250));
    }
  }
  if (!new Set(["PAUSED", "ENDED", "ERROR"]).has(result.state)
    || !result.checkpointed
    || !result.released) {
    throw new Error(t("replay.hub.returnUnconfirmed"));
  }
  navigate("/replay.html");
  return result;
}
