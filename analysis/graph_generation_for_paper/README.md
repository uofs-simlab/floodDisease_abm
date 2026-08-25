# Paper graph generation

Generate the selected paper figures from existing scenario exports:

```powershell
python analysis/graph_generation_for_paper/generate_paper_graphs.py
```

By default, the script reads below `outputs/` and writes 300 dpi PNG files to `outputs/paper_graphs/`. Simulation time-series are displayed in elapsed days by default, with ticks every three days. It discovers both flat exports and the current nested folders such as `baseline/baseline_1500x15/` and `flood_only/floodonly_1500x15/`.

Useful options:

```powershell
python analysis/graph_generation_for_paper/generate_paper_graphs.py --list-figures
python analysis/graph_generation_for_paper/generate_paper_graphs.py --figures compound_finance,compound_affected_populations --time-unit day --time-tick 3
python analysis/graph_generation_for_paper/generate_paper_graphs.py --config analysis/graph_generation_for_paper/paper_graph_config.example.json
python analysis/graph_generation_for_paper/generate_paper_graphs.py --format pdf --dpi 600
```

The editable catalog is `generate_paper_graphs.py`. For repeatable per-figure changes, copy `paper_graph_config.example.json` and override any figure's `filename`, `title`, `xlabel`, `ylabel`, or `series`. Each series entry uses the form `["data_column", "legend label"]`.
