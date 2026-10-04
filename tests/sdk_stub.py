"""Minimal stand-in for the GenLayer SDK so contract logic can run under plain pytest.

This is NOT a consensus simulator. It executes the leader function once, remembers the
validator function, and lets tests call that validator with any leader result they choose.
Real consensus behaviour is covered by tests/test_ledger.py (gltest direct mode).
"""
import importlib.util
import sys
import types
from pathlib import Path


class UserError(Exception):
    def __init__(self, data):
        super().__init__(data)
        self.data = data


class Return:
    def __init__(self, calldata):
        self.calldata = calldata


class TreeMap(dict):
    pass


class DynArray(list):
    pass


class _Contract:
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        for name, annotation in cls.__dict__.get("__annotations__", {}).items():
            kind = getattr(annotation, "__origin__", annotation)
            setattr(obj, name, kind())
        return obj


class StubRuntime:
    """Holds mutable world state: sender, web, model and captured validators."""

    def __init__(self):
        self.captured = []
        self.web = lambda url: types.SimpleNamespace(status=404, body=b"")
        self.model = lambda prompt, **kw: {"scores": {}, "citations": {}}
        self.prompts = []
        self.gl = types.SimpleNamespace(
            Contract=_Contract,
            public=types.SimpleNamespace(write=lambda f: f, view=lambda f: f),
            message=types.SimpleNamespace(sender_address="0xowner", contract_address="0xcontract"),
            vm=types.SimpleNamespace(
                UserError=UserError,
                Return=Return,
                Result=object,
                run_nondet_unsafe=self._run_nondet,
            ),
            nondet=types.SimpleNamespace(
                web=types.SimpleNamespace(get=lambda url: self.web(url)),
                exec_prompt=self._exec_prompt,
            ),
        )

    def _exec_prompt(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return self.model(prompt, **kwargs)

    def _run_nondet(self, leader_fn, validator_fn):
        result = leader_fn()
        self.captured.append((result, leader_fn, validator_fn))
        return result

    def validate(self, leader_result=None):
        """Run the most recent validator against the captured (or supplied) leader result."""
        result, _leader, validator = self.captured[-1]
        return validator(Return(result if leader_result is None else leader_result))


def load_contract(path: str):
    """Load the contract module against the stub, then restore sys.modules."""
    runtime = StubRuntime()
    fake = types.ModuleType("genlayer")
    fake.gl = runtime.gl
    fake.TreeMap = TreeMap
    fake.DynArray = DynArray
    fake.u256 = int
    previous = sys.modules.get("genlayer")
    sys.modules["genlayer"] = fake
    try:
        spec = importlib.util.spec_from_file_location("plumbline_under_test", Path(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            del sys.modules["genlayer"]
        else:
            sys.modules["genlayer"] = previous
    return module, runtime
