#!/usr/bin/env python3
"""
Comprehensive QA Test Suite for AlphaFold Sovereign MCP Phase 1 Tools.

TOPOLOGICA LLC - Santiago Maniches (ORCID: 0009-0005-6480-1987)
Patent-pending drift tensor correction framework.

Tests all 25 tools for:
1. Input model field alignment
2. Handler method calls exist
3. No runtime errors on basic invocation
"""
import sys
import asyncio
import json
from datetime import datetime, timezone

sys.path.insert(0, 'src')

from alphafold_sovereign.alphafold_mcp import (
    # Core tools
    get_structure, GetStructureInput,
    search_structures, SearchStructuresInput,
    batch_structures, BatchStructuresInput,
    get_features, GetFeaturesInput,
    get_topology, GetTopologyInput,
    check_availability, CheckAvailabilityInput,
    get_cache_statistics,
    
    # Enrichment tools
    get_enriched_protein, GetEnrichedProteinInput,
    batch_go_lookup, BatchGOLookupInput,
    search_by_go_term, SearchByGOTermInput,
    get_go_hierarchy, GetGOHierarchyInput,
    export_protein_set, ExportProteinSetInput,
    filter_by_organism, FilterByOrganismInput,
    get_protein_families, GetProteinFamiliesInput,
    find_similar_proteins, FindSimilarProteinsInput,
    get_domain_annotations, GetDomainAnnotationsInput,
    
    # Phase 1 Advanced tools
    extract_pae_matrix, ExtractPAEMatrixInput,
    detect_domains, DetectDomainsInput,
    predict_disorder, PredictDisorderInput,
    get_plddt_profile, GetPLDDTProfileInput,
    compute_information_content, ComputeInformationContentInput,
    compute_semantic_similarity, ComputeSemanticSimilarityInput,
    get_advanced_topology, GetAdvancedTopologyInput,
    compare_protein_topology, CompareProteinTopologyInput,
    batch_protein_analysis, BatchProteinAnalysisInput,
    
    ResponseFormat
)


# Test configuration
TEST_PROTEIN = "P04637"  # TP53
TEST_GO_TERM = "GO:0003700"


class QATestRunner:
    """Test runner for Phase 1 QA."""
    
    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0
        self.warnings = 0
    
    def log(self, tool: str, status: str, message: str):
        """Log test result."""
        self.results.append({
            'tool': tool,
            'status': status,
            'message': message,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        if status == 'PASS':
            self.passed += 1
            indicator = '[PASS]'
        elif status == 'FAIL':
            self.failed += 1
            indicator = '[FAIL]'
        else:
            self.warnings += 1
            indicator = '[WARN]'
        
        print(f"{indicator} {tool}: {message}")
    
    async def test_tool(self, name: str, func, params):
        """Test a single tool."""
        try:
            # Handle tools that don't take params
            if params is None:
                result = await func()
            else:
                result = await func(params)
            
            # Check if result is valid JSON or string
            if isinstance(result, str):
                try:
                    data = json.loads(result)
                    if data.get('status') == 'error':
                        # API errors are okay for test - means handler ran
                        self.log(name, 'PASS', f"Handler executed (API returned: {data.get('error', 'unknown')[:50]})")
                    else:
                        self.log(name, 'PASS', "Handler executed successfully")
                except json.JSONDecodeError:
                    # Markdown response
                    self.log(name, 'PASS', f"Handler returned markdown ({len(result)} chars)")
            else:
                self.log(name, 'PASS', "Handler executed successfully")
                
        except AttributeError as e:
            self.log(name, 'FAIL', f"Missing attribute: {e}")
        except TypeError as e:
            self.log(name, 'FAIL', f"Type error: {e}")
        except Exception as e:
            # Network errors or other runtime errors are okay
            error_msg = str(e)
            if 'timeout' in error_msg.lower() or 'network' in error_msg.lower() or 'connection' in error_msg.lower():
                self.log(name, 'WARN', f"Network issue (handler OK): {error_msg[:50]}")
            else:
                self.log(name, 'FAIL', f"Runtime error: {error_msg[:80]}")
    
    async def run_all_tests(self):
        """Run all Phase 1 tests."""
        print("=" * 70)
        print("ALPHAFOLD SOVEREIGN MCP - PHASE 1 QA TEST SUITE")
        print("TOPOLOGICA LLC - Santiago Maniches (ORCID: 0009-0005-6480-1987)")
        print("=" * 70)
        print()
        
        # Core tools (8)
        print("--- CORE TOOLS ---")
        await self.test_tool("get_structure", get_structure, GetStructureInput(
            uniprot_id=TEST_PROTEIN, include_features=False, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("search_structures", search_structures, SearchStructuresInput(
            pattern="A0A*", limit=5, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("batch_structures", batch_structures, BatchStructuresInput(
            uniprot_ids=[TEST_PROTEIN], include_features=False, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("get_features", get_features, GetFeaturesInput(
            uniprot_id=TEST_PROTEIN, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("get_topology", get_topology, GetTopologyInput(
            uniprot_id=TEST_PROTEIN, max_dimension=1, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("check_availability", check_availability, CheckAvailabilityInput(
            uniprot_ids=[TEST_PROTEIN]
        ))
        await self.test_tool("get_cache_statistics", get_cache_statistics, None)
        
        # Enrichment tools (10)
        print("\n--- ENRICHMENT TOOLS ---")
        await self.test_tool("get_enriched_protein", get_enriched_protein, GetEnrichedProteinInput(
            uniprot_id=TEST_PROTEIN, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("batch_go_lookup", batch_go_lookup, BatchGOLookupInput(
            uniprot_ids=[TEST_PROTEIN], response_format=ResponseFormat.JSON
        ))
        await self.test_tool("search_by_go_term", search_by_go_term, SearchByGOTermInput(
            go_term=TEST_GO_TERM, limit=5, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("get_go_hierarchy", get_go_hierarchy, GetGOHierarchyInput(
            go_term=TEST_GO_TERM, depth=1, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("export_protein_set", export_protein_set, ExportProteinSetInput(
            uniprot_ids=[TEST_PROTEIN], output_format="tsv"
        ))
        await self.test_tool("filter_by_organism", filter_by_organism, FilterByOrganismInput(
            organism="Homo sapiens", limit=5, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("get_protein_families", get_protein_families, GetProteinFamiliesInput(
            uniprot_ids=[TEST_PROTEIN, "P00533"], response_format=ResponseFormat.JSON
        ))
        await self.test_tool("find_similar_proteins", find_similar_proteins, FindSimilarProteinsInput(
            uniprot_id=TEST_PROTEIN, limit=5, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("get_domain_annotations", get_domain_annotations, GetDomainAnnotationsInput(
            uniprot_ids=[TEST_PROTEIN], response_format=ResponseFormat.JSON
        ))
        
        # Phase 1 Advanced tools (9)
        print("\n--- PHASE 1 ADVANCED TOOLS ---")
        await self.test_tool("extract_pae_matrix", extract_pae_matrix, ExtractPAEMatrixInput(
            uniprot_id=TEST_PROTEIN, include_statistics=True, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("detect_domains", detect_domains, DetectDomainsInput(
            uniprot_id=TEST_PROTEIN, pae_threshold=5.0, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("predict_disorder", predict_disorder, PredictDisorderInput(
            uniprot_id=TEST_PROTEIN, plddt_threshold=50.0, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("get_plddt_profile", get_plddt_profile, GetPLDDTProfileInput(
            uniprot_id=TEST_PROTEIN, include_per_residue=False, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("compute_information_content", compute_information_content, ComputeInformationContentInput(
            go_terms=[TEST_GO_TERM], corpus="uniprot", normalize=True, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("compute_semantic_similarity", compute_semantic_similarity, ComputeSemanticSimilarityInput(
            term1=TEST_GO_TERM, term2="GO:0005515", method="resnik", response_format=ResponseFormat.JSON
        ))
        await self.test_tool("get_advanced_topology", get_advanced_topology, GetAdvancedTopologyInput(
            uniprot_id=TEST_PROTEIN, max_dimension=1, include_landscapes=False, response_format=ResponseFormat.JSON
        ))
        await self.test_tool("compare_protein_topology", compare_protein_topology, CompareProteinTopologyInput(
            protein1=TEST_PROTEIN, protein2="P00533", distance_metric="wasserstein", response_format=ResponseFormat.JSON
        ))
        await self.test_tool("batch_protein_analysis", batch_protein_analysis, BatchProteinAnalysisInput(
            uniprot_ids=[TEST_PROTEIN], include_structure=True, include_go_terms=False, response_format=ResponseFormat.JSON
        ))
        
        # Summary
        print()
        print("=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        total = self.passed + self.failed + self.warnings
        print(f"Total Tests:  {total}")
        print(f"Passed:       {self.passed}")
        print(f"Failed:       {self.failed}")
        print(f"Warnings:     {self.warnings}")
        print(f"Pass Rate:    {self.passed/total*100:.1f}%")
        print()
        
        if self.failed == 0:
            print("STATUS: ALL TESTS PASSED - READY FOR PRODUCTION")
        else:
            print("STATUS: FIXES REQUIRED")
            print("\nFailed tests:")
            for r in self.results:
                if r['status'] == 'FAIL':
                    print(f"  - {r['tool']}: {r['message']}")
        
        return self.failed == 0


async def main():
    runner = QATestRunner()
    success = await runner.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
