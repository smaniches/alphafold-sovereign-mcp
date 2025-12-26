"""
PHASE 1 BUGFIX SCRIPT
Santiago Maniches (ORCID: 0009-0005-6480-1987) - TOPOLOGICA LLC

This script patches all Phase 1 bugs identified during QA testing.
Run this to generate the fixed code sections.
"""

# ===========================================================================
# BUG #1: Missing helper functions for Phase 1 tools
# Add these after the existing get_advanced_topology() function around line 3165
# ===========================================================================

MISSING_HELPERS = '''
# ===========================================================================
# PHASE 1 HELPER FUNCTIONS - LAZY LOADED INSTANCES
# ===========================================================================

_disorder_predictor: Optional['DisorderPredictor'] = None
_domain_detector: Optional['DomainDetector'] = None
_topology_computer: Optional['AdvancedTopologyComputer'] = None


def get_disorder_predictor() -> 'DisorderPredictor':
    """Get or create disorder predictor instance."""
    global _disorder_predictor
    if _disorder_predictor is None:
        _disorder_predictor = DisorderPredictor()
    return _disorder_predictor


def get_domain_detector() -> 'DomainDetector':
    """Get or create domain detector instance."""
    global _domain_detector
    if _domain_detector is None:
        _domain_detector = DomainDetector()
    return _domain_detector


def get_topology_computer() -> 'AdvancedTopologyComputer':
    """Get or create topology computer instance."""
    global _topology_computer
    if _topology_computer is None:
        _topology_computer = AdvancedTopologyComputer()
    return _topology_computer


def get_semantic_calculator() -> 'SemanticSimilarityCalculator':
    """Alias for get_similarity_calculator for API consistency."""
    return get_similarity_calculator()


def extract_plddt_from_pdb(pdb_path: str) -> List[float]:
    """
    Extract per-residue pLDDT values from PDB file.
    
    In AlphaFold PDB files, pLDDT is stored in the B-factor column.
    Returns list of pLDDT values, one per residue (CA atoms).
    """
    plddt_values = []
    current_residue = None
    
    try:
        with open(pdb_path, 'r') as f:
            for line in f:
                if line.startswith('ATOM') and line[12:16].strip() == 'CA':
                    residue_num = int(line[22:26].strip())
                    if residue_num != current_residue:
                        current_residue = residue_num
                        # B-factor column is 60-66
                        plddt = float(line[60:66].strip())
                        plddt_values.append(plddt)
    except Exception as e:
        logger.error(f"Error extracting pLDDT from {pdb_path}: {e}")
        return []
    
    return plddt_values
'''

# ===========================================================================
# BUG #2: Input models missing fields - Add these fields
# ===========================================================================

INPUT_MODEL_FIXES = '''
# Add to GetPLDDTProfileInput class:
    include_per_residue: bool = Field(
        default=False,
        description="Include per-residue pLDDT values in output"
    )

# Add to ComputeInformationContentInput class:
    normalize: bool = Field(
        default=True,
        description="Normalize IC values to [0, 1] range"
    )

# Add to GetAdvancedTopologyInput class:
    include_landscapes: bool = Field(
        default=False,
        description="Include persistence landscapes"
    )
    include_images: bool = Field(
        default=False,
        description="Include persistence images"
    )
    n_landscapes: int = Field(
        default=5,
        description="Number of landscape functions",
        ge=1,
        le=20
    )
    image_resolution: int = Field(
        default=50,
        description="Resolution for persistence images",
        ge=10,
        le=200
    )

# Add to BatchProteinAnalysisInput class:
    include_features: bool = Field(
        default=True,
        description="Include structural features"
    )
    include_domains: bool = Field(
        default=False,
        description="Include domain detection"
    )
'''

# ===========================================================================
# BUG #3: compare_protein_topology uses wrong attribute names
# ===========================================================================

COMPARE_TOPOLOGY_FIX = '''
# WRONG (line ~5209):
        id1 = params.uniprot_id1.upper().strip()
        id2 = params.uniprot_id2.upper().strip()

# CORRECT:
        id1 = params.protein1.upper().strip()
        id2 = params.protein2.upper().strip()
'''

# ===========================================================================
# BUG #4: compute_semantic_similarity uses wrong attributes
# ===========================================================================

SEMANTIC_SIMILARITY_FIX = '''
# WRONG:
        similarity = calculator.compute_similarity(
            terms1=params.terms1,
            terms2=params.terms2 or params.terms1,
            method=params.method,
            ontology=params.ontology
        )

# CORRECT:
        similarity = calculator.compute_similarity(
            term1=params.term1,
            term2=params.term2,
            method=params.method
        )
'''

# ===========================================================================
# BUG #5: compute_information_content uses wrong attribute
# ===========================================================================

IC_FIX = '''
# WRONG:
            ic_value = calculator.compute_ic(
                go_term,
                corpus=params.corpus,
                normalize=params.normalize
            )

# CORRECT:
            ic_value = calculator.compute_ic(
                go_term,
                corpus=params.corpus
            )
'''

# ===========================================================================
# BUG #6: Structure path not in JSON response - Fix format_structure_response
# ===========================================================================

STRUCTURE_RESPONSE_FIX = '''
# In format_structure_response, ensure pdb_path is included:
def format_structure_response(
    structure: AlphaFoldStructure,
    features: Optional[Dict[str, Any]] = None,
    topology: Optional[Dict[str, Any]] = None,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN
) -> str:
    """Format structure response."""
    if response_format == ResponseFormat.JSON:
        result = {
            "status": "success",
            "structure": {
                "uniprot_id": structure.uniprot_id,
                "organism": structure.organism,
                "sequence_length": structure.n_residues,
                "n_atoms": structure.n_atoms,
                "mean_plddt": structure.mean_plddt,
                "source": structure.source,
                "pdb_path": str(structure.pdb_path) if hasattr(structure, 'pdb_path') else None
            }
        }
        if features:
            result['features'] = features
        if topology:
            result['topology'] = topology
        return json.dumps(result, indent=2)
    # ... rest of markdown formatting
'''

# ===========================================================================
# BUG #7: ExtractPAEMatrixInput missing include_statistics and block_size
# ===========================================================================

PAE_INPUT_FIX = '''
# Add to ExtractPAEMatrixInput:
    include_statistics: bool = Field(
        default=True,
        description="Include statistical summary of PAE values"
    )
    block_size: int = Field(
        default=10,
        description="Block size for domain boundary detection",
        ge=5,
        le=50
    )
'''

print("PHASE 1 BUGFIX ANALYSIS COMPLETE")
print("=" * 60)
print("Bugs identified:")
print("1. Missing helper functions: get_disorder_predictor, etc.")
print("2. Input models missing fields")
print("3. compare_protein_topology: wrong attribute names")
print("4. compute_semantic_similarity: wrong attributes")
print("5. compute_information_content: wrong attribute")
print("6. Structure response missing pdb_path")
print("7. ExtractPAEMatrixInput missing fields")
print("=" * 60)
