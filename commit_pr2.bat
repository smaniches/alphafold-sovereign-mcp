@echo off
cd /d C:\Users\santi\Documents\GITHUB_REPOS\alphafold-sovereign-mcp
git add -A
git commit -m "feat(PR2): Add 8 Protein Function Intelligence tools - batch_go_lookup: Get GO terms for 100s of proteins - search_by_go_term: Find proteins by GO annotation - get_go_hierarchy: Navigate GO parent/child relationships - export_protein_set: Export to TSV/CSV for ML pipelines - find_similar_proteins: Sequence/structure similarity search - get_domain_annotations: Pfam/InterPro domains - filter_by_organism: Species-specific protein sets - get_protein_families: Cluster by similarity Includes: GOAnnotationCache (persistent), SequenceDatabase (k-mer search) Total tools: 16 (8 original + 8 new)"
git push origin main
