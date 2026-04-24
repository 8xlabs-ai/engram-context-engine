# sample_workspace

Tiny Python workspace used by `engram smoke-test` and by router / reconciler
fixture tests. Symbol layout is intentional: `Pipeline.process_batch` is the
canonical test symbol — its body exists so Serena can resolve it and
`engram.why` has something to anchor against.

```
sample_workspace/
├── src/
│   ├── pipeline.py      # Pipeline + process_batch
│   ├── parser.py        # Parser.parse_json
│   └── utils.py         # helper functions (overlap intentional)
└── tests/
    └── test_pipeline.py # minimal pytest fixture
```

Do not edit without updating tests that depend on the line ranges and
symbol names.
