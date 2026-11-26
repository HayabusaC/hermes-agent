import { INSTALL_STAMP, installShape, type InstallStamp } from './install-stamp'
import { isLightPayload } from './light-remote-only'

export function bootstrapSnapshot<State>(
  state: State,
  stamp: Readonly<InstallStamp> | null = INSTALL_STAMP
): State & { bundled: boolean; remoteOnly: boolean } {
  return {
    ...state,
    bundled: installShape(stamp) === 'bundled',
    // A light artifact has no local runtime: the renderer never paints a local
    // install or a repair, only the remote connect form.
    remoteOnly: isLightPayload(stamp?.payload)
  }
}
