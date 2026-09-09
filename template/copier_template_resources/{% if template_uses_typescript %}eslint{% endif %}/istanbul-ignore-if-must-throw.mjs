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

// A block's last statement doesn't prove it always throws: a nested `if` with no `else` can
// return before a later throw is ever reached. These two functions walk `if`/block nesting to
// check that every reachable path throws.
function stmtAlwaysThrows(stmt) {
  if (stmt.type === "ThrowStatement") return true;
  if (stmt.type === "BlockStatement") return blockAlwaysThrows(stmt.body);
  if (stmt.type === "IfStatement") {
    return stmt.alternate !== null && stmtAlwaysThrows(stmt.consequent) && stmtAlwaysThrows(stmt.alternate);
  }
  return false;
}

function stmtMayReturnWithoutThrowing(stmt) {
  if (stmt.type === "ReturnStatement") return true;
  if (stmt.type === "ThrowStatement") return false;
  if (stmt.type === "BlockStatement") return blockMayReturnWithoutThrowing(stmt.body);
  if (stmt.type === "IfStatement") {
    if (stmtAlwaysThrows(stmt.consequent)) {
      return stmt.alternate !== null && stmtMayReturnWithoutThrowing(stmt.alternate);
    }
    return (
      stmtMayReturnWithoutThrowing(stmt.consequent) ||
      (stmt.alternate !== null && stmtMayReturnWithoutThrowing(stmt.alternate))
    );
  }
  return false;
}

function blockAlwaysThrows(body) {
  for (const stmt of body) {
    if (stmtAlwaysThrows(stmt)) return true;
    if (stmtMayReturnWithoutThrowing(stmt)) return false;
  }
  return false;
}

function blockMayReturnWithoutThrowing(body) {
  for (const stmt of body) {
    if (stmtAlwaysThrows(stmt)) return false;
    if (stmtMayReturnWithoutThrowing(stmt)) return true;
  }
  return false;
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
    return {
      IfStatement(node) {
        const leading = sourceCode.getCommentsBefore(node);
        const ignoreComment = leading.find((comment) => IGNORE_IF_OR_NEXT.test(comment.value));
        if (ignoreComment === undefined) return;
        if (RETURN_OK.test(ignoreComment.value)) return;
        if (stmtAlwaysThrows(node.consequent)) return;
        context.report({ node, messageId: "mustThrow" });
      },
    };
  },
};
