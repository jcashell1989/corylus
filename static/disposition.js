/* Hermes Review — stage-then-confirm for irreversible dispositions. No DOM. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.HermesReviewDisposition = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const IRREVERSIBLE = ["approve", "noAction", "human"];

  function intent(kind, opts) {
    opts = opts || {};
    const note = opts.note;
    const notBefore = opts.notBefore;
    const staged = opts.staged || null;
    if (kind === "remediate" && note === undefined) {
      return { action: "openNote", kind: "remediate" };
    }
    if (kind === "snooze" && notBefore === undefined && note === undefined) {
      return { action: "openNote", kind: "snooze" };
    }
    if (IRREVERSIBLE.indexOf(kind) !== -1 && staged !== kind) {
      return { action: "stage", kind: kind };
    }
    return { action: "post", kind: kind, note: note, notBefore: notBefore };
  }

  function confirmNote(kind) {
    return kind === "noAction" ? "discarded" : "";
  }

  function onEscape() {
    return { action: "clear" };
  }

  return {
    IRREVERSIBLE: IRREVERSIBLE,
    intent: intent,
    confirmNote: confirmNote,
    onEscape: onEscape
  };
});
