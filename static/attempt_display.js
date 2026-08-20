/* Hermes Review — attempt metadata empty-state labels. No DOM. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.HermesReviewAttempt = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  // git_pointers=false is ambiguous on its own: it's true both for a real
  // non-Git (host-ops) attempt AND for a task with no hermes:attempt
  // metadata at all. has_attempt disambiguates (td-4952a9).
  function noArtifactsText(attempt) {
    if (attempt.git_pointers) {
      return "no artifacts — add git pointers on post-attempt to get a diff here";
    }
    if (attempt.has_attempt) {
      return "no Git pointers on this attempt — non-Git task, nothing to diff";
    }
    return "no attempt metadata on this task yet";
  }

  function noLogText(attempt) {
    if (attempt.git_pointers) {
      return "no run log captured";
    }
    if (attempt.has_attempt) {
      return "no run log captured — non-Git task and no handoff comment found";
    }
    return "no run log captured — no attempt metadata on this task yet";
  }

  return { noArtifactsText: noArtifactsText, noLogText: noLogText };
});
