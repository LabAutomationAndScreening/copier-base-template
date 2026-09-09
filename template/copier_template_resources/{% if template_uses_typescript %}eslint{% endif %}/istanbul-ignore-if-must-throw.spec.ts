import { RuleTester } from "eslint";
import { describe, it } from "vitest";
import rule from "../../../../.config/eslint-rules/istanbul-ignore-if-must-throw.mjs";

RuleTester.describe = describe;
RuleTester.it = it;

const ruleTester = new RuleTester({
  languageOptions: { ecmaVersion: "latest", sourceType: "module" },
});

// RuleTester.run registers its own describe/it blocks and must be called at module top level, not inside a hook.
// eslint-disable-next-line vitest/require-hook
ruleTester.run("istanbul-ignore-if-must-throw", rule, {
  valid: [
    {
      name: "braceless throw",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (typeof x !== "string") throw new Error("bad");\n  return x;\n}`,
    },
    {
      name: "block throw",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    throw new Error("bad");\n  }\n}`,
    },
    {
      name: "silent return allowed with return-ok escape",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve return-ok: absence is valid */\n  if (!x) return;\n}`,
    },
    {
      name: "if without an istanbul ignore comment is untouched",
      code: `function f(x) {\n  if (!x) return;\n}`,
    },
    {
      name: "istanbul ignore next on a non-if statement is left alone",
      code: `/* istanbul ignore next -- @preserve */\nfunction unreachable() {\n  return 1;\n}`,
    },
    {
      name: "istanbul ignore else is left alone",
      code: `function f(x) {\n  /* istanbul ignore else -- @preserve */\n  if (!x) {\n    doSomething();\n  } else {\n    doOther();\n  }\n}`,
    },
    {
      name: "nested if/else where both branches always throw",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    if (x === null) {\n      throw new Error("null");\n    } else {\n      throw new Error("bad");\n    }\n  }\n}`,
    },
    {
      name: "non-exiting nested if followed by a real throw",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    if (x === null) {\n      logIt();\n    }\n    throw new Error("bad");\n  }\n}`,
    },
    {
      name: "try and catch both always throw",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    try {\n      throw new Error("a");\n    } catch {\n      throw new Error("b");\n    }\n  }\n}`,
    },
    {
      name: "finally always throws regardless of the try block",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    try {\n      doStuff();\n    } finally {\n      throw new Error("bad");\n    }\n  }\n}`,
    },
    {
      name: "switch with a default where every case always throws",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    switch (x) {\n      case 1:\n        throw new Error("one");\n      default:\n        throw new Error("other");\n    }\n  }\n}`,
    },
    {
      name: "break inside switch cases is absorbed, real throw follows",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    switch (x) {\n      case 1:\n        doStuff();\n        break;\n      default:\n        doOther();\n    }\n    throw new Error("bad");\n  }\n}`,
    },
    {
      name: "return inside a nested function belongs to that function, real throw follows",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    const describe = () => {\n      return "missing";\n    };\n    throw new Error(describe());\n  }\n}`,
    },
    {
      name: "break inside a nested loop is absorbed, real throw follows",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    for (const item of items) {\n      if (bad(item)) break;\n    }\n    throw new Error("bad");\n  }\n}`,
    },
  ],
  invalid: [
    {
      name: "silent return under istanbul ignore if",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) return;\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
    {
      name: "block that does not end in throw",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    doSomething();\n  }\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
    {
      name: "silent return under istanbul ignore next on an if",
      code: `function f(x) {\n  /* istanbul ignore next -- @preserve */\n  if (!x) return;\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
    {
      name: "recoverable return reachable before a final throw",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    if (x === null) return;\n    throw new Error("bad");\n  }\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
    {
      name: "nested if throws but its else silently returns",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    if (x === null) {\n      throw new Error("null");\n    } else {\n      return;\n    }\n  }\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
    {
      name: "nested block statement returns silently before a later throw",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    {\n      return;\n    }\n    throw new Error("bad");\n  }\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
    {
      name: "recoverable break reachable before a final throw",
      code: `function f(x) {\n  for (;;) {\n    /* istanbul ignore if -- @preserve */\n    if (!x) {\n      if (x === null) break;\n      throw new Error("bad");\n    }\n  }\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
    {
      name: "recoverable continue reachable before a final throw",
      code: `function f(x) {\n  for (;;) {\n    /* istanbul ignore if -- @preserve */\n    if (!x) {\n      if (x === null) continue;\n      throw new Error("bad");\n    }\n  }\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
    {
      name: "return inside a nested loop reaches past a later throw",
      code: `function f(x) {\n  /* istanbul ignore if -- @preserve */\n  if (!x) {\n    for (const item of items) {\n      if (bad(item)) return;\n    }\n    throw new Error("bad");\n  }\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
    {
      name: "continue inside a switch case is not absorbed by the switch",
      code: `function f(x) {\n  for (;;) {\n    /* istanbul ignore if -- @preserve */\n    if (!x) {\n      switch (x) {\n        case 1:\n          continue;\n        default:\n          break;\n      }\n      throw new Error("bad");\n    }\n  }\n}`,
      errors: [{ messageId: "mustThrow" }],
    },
  ],
});
