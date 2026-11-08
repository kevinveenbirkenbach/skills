const Space = (() => {
  "use strict";
  const {DEFAULTS, LIMITS, AXES, DEPTH, REACH, ease, turn, rotation, apply, camera, project, depthSort, depthOf, notBeforeParent, clampView, tidy, tween, lens, place, horizon, compass} = typeof SpaceView === "object" ? SpaceView : require("./space-view.js");
  const {TONES, ARC_CAP, bend, moon, nameAt, tree, capArcs, scene} = typeof SpaceScene === "object" ? SpaceScene : require("./space-scene.js");
  const {paint} = typeof SpacePaint === "object" ? SpacePaint : require("./space-paint.js");
  const {pick} = typeof SpacePick === "object" ? SpacePick : require("./space-pick.js");

  return {
    DEFAULTS, LIMITS, AXES, TONES, ARC_CAP, DEPTH, REACH,
    ease, turn, bend, moon, rotation, apply, camera, project, depthSort, depthOf, notBeforeParent, clampView, tidy, tween, nameAt, tree, capArcs, scene, paint, pick,
    lens, place, horizon, compass,
  };
})();
if (typeof module === "object" && module.exports) {
  module.exports = Space;
}
