/*
 * Enforces the defensive-assertion contract for coverage-ignored branches:
 *
 * A branch marked `istanbul ignore if` (or `istanbul ignore next` when it sits on
 * an `if`) must throw. Coverage-ignoring a guard means "this is unreachable"; a
 * silent `return` there hides a real bug instead of surfacing it. If a silent exit
 * is genuinely intentional, the author must opt out with `return-ok` in the ignore
 * comment. Ignore comments on anything other than an `if` are left alone — the rule
 * only makes a claim about branches whose shape it can verify.
 */

const IGNORE_IF_OR_NEXT = /istanbul ignore (if|next)\b/;
const RETURN_OK = /\breturn-ok\b/;

const LOOP_TYPES = new Set(["ForStatement", "ForInStatement", "ForOfStatement", "WhileStatement", "DoWhileStatement"]);
// Statements that leave the branch without throwing.
const SILENT_EXIT_TYPES = new Set(["ReturnStatement", "BreakStatement", "ContinueStatement"]);

// "The branch always throws" is two reachability facts, both read off ESLint's code path analysis
// rather than re-deriving control flow here: the end of the consequent must be unreachable, and no
// reachable return/break/continue inside it may target a construct outside it.
function isExitTarget(exit, ancestor) {
  if (exit.label !== null) {
    return ancestor.type === "LabeledStatement" && ancestor.label.name === exit.label.name;
  }
  if (exit.type === "BreakStatement") return LOOP_TYPES.has(ancestor.type) || ancestor.type === "SwitchStatement";
  return LOOP_TYPES.has(ancestor.type);
}

function exitEscapesBranch(exit, consequent) {
  if (exit.type === "ReturnStatement") return true;
  for (let cur = exit.parent; cur !== consequent.parent; cur = cur.parent) {
    if (isExitTarget(exit, cur)) return false;
  }
  return true;
}

/** @type {import("eslint").Rule.RuleModule} */
export default {
  meta: {
    type: "problem",
    docs: {
      description: "Require `istanbul ignore if` branches to throw a defensive assertion",
    },
    schema: [],
    messages: {
      mustThrow:
        "A branch marked `istanbul ignore if` must throw a defensive assertion. If a silent return is intentional, add `return-ok` to the ignore comment.",
    },
  },
  create(context) {
    const sourceCode = context.sourceCode;
    const segmentStacks = [];
    // Ignored ifs can nest, and AST traversal is depth-first, so the innermost branch under check is
    // always the top of this stack; it's popped when its consequent ends.
    const branchStack = [];

    function isReachable() {
      return [...segmentStacks.at(-1)].some((segment) => segment.reachable);
    }

    function report(entry) {
      if (entry.reported) return;
      entry.reported = true;
      context.report({ node: entry.node, messageId: "mustThrow" });
    }

    function onSilentExit(node) {
      const entry = branchStack.at(-1);
      // Depth check keeps exits inside a nested function (its own code path) from counting.
      if (entry === undefined || entry.depth !== segmentStacks.length) return;
      if (isReachable() && exitEscapesBranch(node, entry.consequent)) report(entry);
    }

    return {
      onCodePathStart() {
        segmentStacks.push(new Set());
      },
      onCodePathEnd() {
        segmentStacks.pop();
      },
      onCodePathSegmentStart(segment) {
        segmentStacks.at(-1).add(segment);
      },
      onCodePathSegmentEnd(segment) {
        segmentStacks.at(-1).delete(segment);
      },
      onUnreachableCodePathSegmentStart(segment) {
        segmentStacks.at(-1).add(segment);
      },
      onUnreachableCodePathSegmentEnd(segment) {
        segmentStacks.at(-1).delete(segment);
      },
      IfStatement(node) {
        const leading = sourceCode.getCommentsBefore(node);
        const ignoreComment = leading.find((comment) => IGNORE_IF_OR_NEXT.test(comment.value));
        if (ignoreComment === undefined) return;
        if (RETURN_OK.test(ignoreComment.value)) return;
        branchStack.push({ node, consequent: node.consequent, depth: segmentStacks.length, reported: false });
      },
      ":statement:exit"(node) {
        if (node !== branchStack.at(-1)?.consequent) return;
        const entry = branchStack.pop();
        // ESLint applies a throw/return/break/continue to the code path only after emitting that
        // node's :exit, so for a braceless consequent the segments seen here are still the ones
        // from before it. A bare throw satisfies the rule; a bare silent exit was already judged
        // by onSilentExit on entry.
        const { type } = entry.consequent;
        if (type === "ThrowStatement" || SILENT_EXIT_TYPES.has(type)) return;
        if (isReachable()) report(entry);
      },
      ReturnStatement: onSilentExit,
      BreakStatement: onSilentExit,
      ContinueStatement: onSilentExit,
    };
  },
};
