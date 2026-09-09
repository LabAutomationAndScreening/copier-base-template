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

function consequentAlwaysThrows(consequent) {
  if (consequent.type === "ThrowStatement") return true;
  if (consequent.type === "BlockStatement") {
    const last = consequent.body.at(-1);
    return last !== undefined && last.type === "ThrowStatement";
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
        if (consequentAlwaysThrows(node.consequent)) return;
        context.report({ node, messageId: "mustThrow" });
      },
    };
  },
};
