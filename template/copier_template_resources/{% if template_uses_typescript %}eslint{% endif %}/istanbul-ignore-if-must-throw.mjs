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

// A block's last statement doesn't prove it always throws: a nested `if` with no `else` can
// return before a later throw is ever reached. stmtAlwaysThrows/blockAlwaysThrows walk if/block/
// try/switch nesting to check every path throws.
//
// exitKinds/blockExitKinds track which silent exits (return/break/continue/an unresolvable
// labeled jump) are reachable. break/continue don't escape like return does: a loop absorbs both,
// a switch absorbs only break, so loopExitKinds/switchExitKinds strip those out before bubbling up.
// A labeled break/continue is conservatively treated as always escaping (safe direction: a missed
// report, not a missed bug).
function stmtAlwaysThrows(stmt) {
  if (stmt.type === "ThrowStatement") return true;
  if (stmt.type === "BlockStatement") return blockAlwaysThrows(stmt.body);
  if (stmt.type === "LabeledStatement") return stmtAlwaysThrows(stmt.body);
  if (stmt.type === "IfStatement") {
    return stmt.alternate !== null && stmtAlwaysThrows(stmt.consequent) && stmtAlwaysThrows(stmt.alternate);
  }
  if (stmt.type === "TryStatement") return tryAlwaysThrows(stmt);
  if (stmt.type === "SwitchStatement") return switchAlwaysThrows(stmt);
  return false;
}

function tryAlwaysThrows(node) {
  // A return/break/continue in finally overrides try/catch entirely, per JS semantics.
  if (node.finalizer !== null) {
    if (stmtAlwaysThrows(node.finalizer)) return true;
    if (exitKinds(node.finalizer).size > 0) return false;
  }
  const blockThrows = stmtAlwaysThrows(node.block);
  const handlerThrows = node.handler === null ? true : stmtAlwaysThrows(node.handler.body);
  return blockThrows && handlerThrows;
}

function switchAlwaysThrows(node) {
  // Doesn't trace case fallthrough; requires every case (default included) to throw on its own.
  // Errs toward false positives on a legitimately-throwing fallthrough switch, never false negatives.
  if (!node.cases.some((c) => c.test === null)) return false;
  return node.cases.every((c) => blockAlwaysThrows(c.consequent));
}

function exitKinds(stmt) {
  if (stmt.type === "ReturnStatement") return new Set(["return"]);
  if (stmt.type === "BreakStatement") return new Set([stmt.label === null ? "break" : "labeled"]);
  if (stmt.type === "ContinueStatement") return new Set([stmt.label === null ? "continue" : "labeled"]);
  if (stmt.type === "ThrowStatement") return new Set();
  if (stmt.type === "BlockStatement") return blockExitKinds(stmt.body);
  if (stmt.type === "LabeledStatement") return exitKinds(stmt.body);
  if (stmt.type === "IfStatement") {
    const consequentKinds = stmtAlwaysThrows(stmt.consequent) ? new Set() : exitKinds(stmt.consequent);
    const alternateKinds =
      stmt.alternate === null || stmtAlwaysThrows(stmt.alternate) ? new Set() : exitKinds(stmt.alternate);
    return union(consequentKinds, alternateKinds);
  }
  if (stmt.type === "TryStatement") return tryExitKinds(stmt);
  if (stmt.type === "SwitchStatement") return switchExitKinds(stmt);
  if (LOOP_TYPES.has(stmt.type)) return withoutKinds(exitKinds(stmt.body), ["break", "continue"]);
  return new Set();
}

function tryExitKinds(node) {
  if (node.finalizer !== null) {
    if (stmtAlwaysThrows(node.finalizer)) return new Set();
    const finallyKinds = exitKinds(node.finalizer);
    if (finallyKinds.size > 0) return finallyKinds;
  }
  const blockKinds = stmtAlwaysThrows(node.block) ? new Set() : exitKinds(node.block);
  const handlerKinds =
    node.handler === null || stmtAlwaysThrows(node.handler.body) ? new Set() : exitKinds(node.handler.body);
  return union(blockKinds, handlerKinds);
}

function switchExitKinds(node) {
  let kinds = new Set();
  for (const c of node.cases) {
    kinds = union(kinds, blockExitKinds(c.consequent));
  }
  return withoutKinds(kinds, ["break"]);
}

function union(a, b) {
  return new Set([...a, ...b]);
}

function withoutKinds(kinds, excluded) {
  return new Set([...kinds].filter((kind) => !excluded.includes(kind)));
}

function blockAlwaysThrows(body) {
  for (const stmt of body) {
    if (stmtAlwaysThrows(stmt)) return true;
    if (exitKinds(stmt).size > 0) return false;
  }
  return false;
}

function blockExitKinds(body) {
  for (const stmt of body) {
    if (stmtAlwaysThrows(stmt)) return new Set();
    const kinds = exitKinds(stmt);
    if (kinds.size > 0) return kinds;
  }
  return new Set();
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
