Summary Report
DatatypeDownloadSourcesRegister/CreateLoadNotesStructure✅ WorksRCSB ✅, AlphaFold ❌ (network)N/A (download handles)✅ WorksAlphaFold fails likely due to network restrictionsSequence✅ WorksUniProt ✅✅ sequence_register_records✅ WorksField must be name not id; preview_length must be ≥200Ligand/Molecule❌ Not supportedN/A⚠️ ligand_register_smiles broken✅ Loads existingUse save_entity with format molecule as workaroundGRNN/AN/A⚠️ add_grn_annotation broken⚠️ load_grn_table brokenReference tables load OK; user tables have bug ('GRNProcessor' object has no attribute 'load_grn_table')PropertyN/AN/A✅ record_property_rows✅ WorksRows require scope as list of {format, name} dictsEmbeddingN/AN/A✅ embedding_generate✅ WorksMultiple ESM2 and Ankh models availableGraphN/AN/A✅ structure_graph_generate_from_dataset✅ WorksGenerates residue/atom-level contact graphs
Key Issues Found

AlphaFold download fails - Likely network restrictions in this environment
ligand_register_smiles - Bug: 'MoleculeProcessor' object has no attribute 'register_smiles_dataset'
GRN loading/modification broken - Bug: 'GRNProcessor' object has no attribute 'load_grn_table'
create_property_table - Wrong parameter name in implementation
load_sequence_dataset - preview_length must be ≥200 (default 120 fails validation)

Working Workarounds

For ligands: Use save_entity with format="molecule"
For properties: Use record_property_rows with allow_create=true
For GRN: Reference tables load fine via load_grn_reference_table; creation via assign_grn_to_dataset likely still works