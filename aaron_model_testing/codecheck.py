"""A bounded interpreter for the small, pure Python functions in agent-core-v1.

Model code is NEVER passed to eval/exec or run on the host. Unsupported syntax fails
explicitly. This deliberately measures a defined Python subset, not general execution.
"""

from __future__ import annotations

import ast
import operator


class Returned(Exception):
    def __init__(self, value):
        self.value = value


class Interpreter:
    def __init__(self, source: str):
        if len(source) > 20000:
            raise ValueError("Code exceeds limit")
        tree = ast.parse(source)
        if any(not isinstance(n, ast.FunctionDef) for n in tree.body):
            raise ValueError("Only function definitions are allowed")
        self.functions = {n.name: n for n in tree.body}
        if not self.functions or any(
            n.decorator_list or n.args.defaults or n.args.kw_defaults for n in tree.body
        ):
            raise ValueError("Decorators/default arguments are unsupported")
        if any(isinstance(n, ast.Name) and n.id.startswith("_") for n in ast.walk(tree)):
            raise ValueError("Private identifiers are forbidden")
        self.steps = 0
        self.depth = 0

    def tick(self, value=None):
        self.steps += 1
        if self.steps > 10000 or (isinstance(value, (str, list, tuple, dict, set)) and len(value) > 1000):
            raise ValueError("Interpreter budget exceeded")
        if isinstance(value, int) and value.bit_length() > 256:
            raise ValueError("Integer exceeds limit")
        return value

    def call(self, name, args):
        self.tick()
        self.depth += 1
        try:
            if self.depth > 10:
                raise ValueError("Call depth exceeded")
            if name in self.functions:
                function = self.functions[name]
                if len(args) != len(function.args.args):
                    raise ValueError("Wrong argument count")
                env = dict(zip([a.arg for a in function.args.args], args))
                try:
                    self.block(function.body, env)
                except Returned as r:
                    return self.tick(r.value)
                return None
            builtins = {
                "len": len,
                "sum": sum,
                "min": min,
                "max": max,
                "abs": abs,
                "sorted": sorted,
                "list": list,
                "set": set,
                "int": int,
                "str": str,
                "enumerate": enumerate,
            }
            if name == "range":
                result = range(*args)
                if len(result) > 1000:
                    raise ValueError("range exceeds limit")
                return result
            if name not in builtins:
                raise ValueError(f"Unsupported function: {name}")
            return self.tick(builtins[name](*args))
        finally:
            self.depth -= 1

    def expression(self, node, env):
        self.tick()
        if isinstance(node, ast.Constant):
            return self.tick(node.value)
        if isinstance(node, ast.Name):
            return env[node.id]
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = [self.expression(n, env) for n in node.elts]
            return self.tick(set(values) if isinstance(node, ast.Set) else values)
        if isinstance(node, ast.Dict):
            return self.tick(
                {self.expression(k, env): self.expression(v, env) for k, v in zip(node.keys, node.values)}
            )
        if isinstance(node, ast.Subscript):
            return self.expression(node.value, env)[self.expression(node.slice, env)]
        if isinstance(node, ast.UnaryOp):
            ops = {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}
            return self.tick(ops[type(node.op)](self.expression(node.operand, env)))
        if isinstance(node, ast.BinOp):
            ops = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
                ast.Div: operator.truediv,
            }
            left, right = self.expression(node.left, env), self.expression(node.right, env)
            if isinstance(node.op, ast.Mult) and (
                isinstance(left, (list, str, tuple))
                and isinstance(right, int)
                and len(left) * right > 1000
                or isinstance(right, (list, str, tuple))
                and isinstance(left, int)
                and len(right) * left > 1000
            ):
                raise ValueError("Multiplication exceeds limit")
            return self.tick(ops[type(node.op)](left, right))
        if isinstance(node, ast.Compare):
            ops = {
                ast.Eq: operator.eq,
                ast.NotEq: operator.ne,
                ast.Lt: operator.lt,
                ast.LtE: operator.le,
                ast.Gt: operator.gt,
                ast.GtE: operator.ge,
                ast.In: lambda a, b: a in b,
                ast.NotIn: lambda a, b: a not in b,
                ast.Is: operator.is_,
                ast.IsNot: operator.is_not,
            }
            left = self.expression(node.left, env)
            for op, comparator in zip(node.ops, node.comparators):
                right = self.expression(comparator, env)
                if not ops[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            value = None
            for item in node.values:
                value = self.expression(item, env)
                if isinstance(node.op, ast.And) and not value or isinstance(node.op, ast.Or) and value:
                    return value
            return value
        if isinstance(node, ast.IfExp):
            return self.expression(node.body if self.expression(node.test, env) else node.orelse, env)
        if isinstance(node, ast.Call):
            if node.keywords:
                raise ValueError("Keyword calls are unsupported in v1")
            args = [self.expression(a, env) for a in node.args]
            if isinstance(node.func, ast.Name):
                return self.call(node.func.id, args)
            if isinstance(node.func, ast.Attribute):
                target = self.expression(node.func.value, env)
                if isinstance(target, list) and node.func.attr == "append" and len(args) == 1:
                    target.append(args[0])
                    self.tick(target)
                    return None
                if isinstance(target, set) and node.func.attr == "add" and len(args) == 1:
                    target.add(args[0])
                    self.tick(target)
                    return None
            raise ValueError("Unsupported method call")
        raise ValueError(f"Unsupported expression: {type(node).__name__}")

    def assign(self, target, value, env):
        if isinstance(target, ast.Name):
            env[target.id] = self.tick(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            if len(target.elts) != len(value):
                raise ValueError("Unpack mismatch")
            for t, v in zip(target.elts, value):
                self.assign(t, v, env)
        else:
            raise ValueError("Unsupported assignment")

    def block(self, nodes, env):
        for node in nodes:
            self.tick()
            if isinstance(node, ast.Return):
                raise Returned(self.expression(node.value, env) if node.value else None)
            if isinstance(node, ast.Assign):
                value = self.expression(node.value, env)
                for target in node.targets:
                    self.assign(target, value, env)
            elif isinstance(node, ast.AugAssign):
                value = self.expression(ast.BinOp(left=node.target, op=node.op, right=node.value), env)
                self.assign(node.target, value, env)
            elif isinstance(node, ast.If):
                self.block(node.body if self.expression(node.test, env) else node.orelse, env)
            elif isinstance(node, ast.For):
                for value in self.expression(node.iter, env):
                    self.assign(node.target, value, env)
                    self.block(node.body, env)
            elif isinstance(node, ast.Expr):
                self.expression(node.value, env)
            elif isinstance(node, ast.Pass):
                pass
            else:
                raise ValueError(f"Unsupported statement: {type(node).__name__}")


def check_code(source: str, rule: dict):
    interpreter = Interpreter(source)
    outcomes = []
    for case in rule["cases"]:
        interpreter.steps = 0
        got = interpreter.call(rule["function"], case["args"])
        outcomes.append(
            {
                "args": case["args"],
                "expected": case["expected"],
                "actual": got,
                "passed": got == case["expected"],
            }
        )
    return outcomes
