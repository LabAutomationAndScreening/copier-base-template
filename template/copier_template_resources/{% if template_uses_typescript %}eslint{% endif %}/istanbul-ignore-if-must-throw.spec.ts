import { RuleTester } from "eslint";
import { describe, it } from "vitest";
import rule from "../../../../.config/eslint-rules/istanbul-ignore-if-must-throw.mjs";

RuleTester.describe = describe;
RuleTester.it = it;

const ruleTester = new RuleTester({
  languageOptions: { ecmaVersion: 2022, sourceType: "module" },
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
  ],
});
