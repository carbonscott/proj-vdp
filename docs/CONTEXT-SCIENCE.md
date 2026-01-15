# Science Context: VDP Synthetic Magnetics Database

**Date:** January 2026
**Project:** MAIQMag / VDP Tiled Catalog

---

## 1. Overview

The Virtual Data Products (VDP) catalog contains **synthetic quantum spin lattice simulations** generated using [Sunny.jl](https://github.com/SunnySuite/Sunny.jl). The purpose is to create training data for machine learning models that solve the **inverse problem**: given experimental observables (magnetization curves, neutron scattering spectra), infer the underlying Hamiltonian parameters.

---

## 2. The Physical System

### Crystal Structure

| Property | Value |
|----------|-------|
| Lattice type | Orthorhombic |
| Lattice parameters | a = 4.1 Å, b = 4.2 Å, c = 4.3 Å |
| Magnetic ion | Fe²⁺ (iron), single site per unit cell |
| Spin quantum number | S = 5/2 (typical for Fe²⁺) |
| Landé g-factor | g = 2.0 |
| Supercell | 2 × 2 × 2 (8 magnetic sites) |

### Spin Hamiltonian

The model Hamiltonian includes two types of magnetic interactions:

**1. Heisenberg Exchange Interactions** (between neighboring spins):
```
H_exchange = Ja Σ Si·Sj  (along a-axis)
           + Jb Σ Si·Sj  (along b-axis)
           + Jc Σ Si·Sj  (along c-axis)
```

**2. Single-Ion Anisotropy** (onsite crystal field term):
```
H_anisotropy = Dc Σ (Sz)²
```

The full Hamiltonian is: **H = H_exchange + H_anisotropy**

---

## 3. Hamiltonian Parameters

Four parameters define each Hamiltonian instance, sampled via Latin Hypercube Sampling (LHS) across the parameter space:

| Parameter | Physical Meaning | Range | Units |
|-----------|------------------|-------|-------|
| `Ja_meV` | Exchange coupling along a-axis | [-1, 1] | meV |
| `Jb_meV` | Exchange coupling along b-axis | [-1, 1] | meV |
| `Jc_meV` | Exchange coupling along c-axis | [-1, 1] | meV |
| `Dc_meV` | Single-ion anisotropy | [-1, 1] | meV |

### Physical Interpretation

**Exchange Couplings (Ja, Jb, Jc):**
- **J > 0**: Ferromagnetic coupling — neighboring spins prefer **parallel** alignment
- **J < 0**: Antiferromagnetic coupling — neighboring spins prefer **antiparallel** alignment
- Different values along each axis model anisotropic magnetic interactions

**Single-Ion Anisotropy (Dc):**
- **Dc < 0**: Easy-axis anisotropy — spins prefer to point **along z-axis**
- **Dc > 0**: Easy-plane anisotropy — spins prefer to lie **in the xy-plane**

### Magnetic Phases from Parameter Combinations

| Ja, Jb, Jc | Dc | Expected Behavior |
|------------|-----|-------------------|
| All > 0 | < 0 | Ferromagnet with moments along z |
| All < 0 | < 0 | Antiferromagnet (Néel order) with easy axis |
| Mixed signs | Any | Frustrated/competing interactions |
| Any | > 0 | Easy-plane magnet (moments in xy) |

---

## 4. Computed Observables (Artifact Types)

Each Hamiltonian generates multiple artifacts representing different experimental observables:

### 4.1 Magnetization Curves (`mh_curve`)

**What it is:** The material's magnetization response to an applied magnetic field M(H).

**Physical process:** As external field H increases from 0, spins gradually rotate to align with the field direction, increasing net magnetization M until saturation (all spins parallel to field).

| Property | Value |
|----------|-------|
| Output | M∥(H) — magnetization parallel to field |
| Units | μB/spin (Bohr magnetons per spin) |
| Field directions | x, y, z axes + powder average |
| Field ranges | 0–7 T and 0–30 T |
| Grid points | 200 per curve |
| Temperature | 0 K (ground state) |

**Measurement variants:**
- **Powder average**: Spherical average over all field directions (matches polycrystalline samples)
- **Single-crystal (x, y, z)**: Field along specific crystal axis (reveals anisotropy)

**Experimental analog:** Vibrating sample magnetometry (VSM), SQUID magnetometry

**Normalization:** Curves are normalized as m(h) = M/(g·S), where h = H/Hmax ∈ [0, 1]

### 4.2 Inelastic Neutron Scattering (`ins_powder`)

**What it is:** The dynamic structure factor S(Q,ω) — scattering intensity as a function of momentum transfer Q and energy transfer ω.

**Physical process:** Incident neutrons exchange energy and momentum with magnetic excitations (magnons/spin waves) in the material. The scattering pattern maps out the magnon dispersion relation ω(Q).

| Property | Value |
|----------|-------|
| Output | S(Q,ω) — scattering intensity |
| Incident energies | Ei = 12 meV and 25 meV |
| Q grid | 600 points |
| Energy grid | ~400 points |
| Processing variants | Sharp (ideal), broadened (with resolution), masked (detector coverage) |

**Resolution modeling:** Uses PyChop-derived energy resolution functions for realistic instrumental broadening (matching CNCS spectrometer at SNS).

**Experimental analog:** Time-of-flight neutron spectrometers (CNCS, ARCS at SNS/ORNL)

**Physics revealed:**
- Magnon dispersion (spin wave energies vs momentum)
- Energy gaps from anisotropy (Dc creates a gap at Q=0)
- Bandwidth related to exchange coupling strength

### 4.3 Ground State (`gs_state`)

**What it is:** The equilibrium spin configuration at zero temperature and zero field.

**Physical process:** Energy minimization finds the lowest-energy arrangement of spin orientations.

| Property | Value |
|----------|-------|
| Output | Spin direction vectors |
| Shape | (3, 8) array — 3D vectors for 8 spins |
| Method | Energy minimization with random restarts |

**Use case:** Understanding magnetic order (ferromagnetic, antiferromagnetic, canted, spiral, etc.)

---

## 5. The Inverse Problem

### Traditional Approach (Manual Fitting)

Determining a spin Hamiltonian from experimental data traditionally requires:

1. **Measure** M(H) curves and/or neutron spectra
2. **Guess** initial Hamiltonian parameters (Ja, Jb, Jc, Dc)
3. **Simulate** forward using Sunny.jl, SpinW, or similar code
4. **Compare** simulated and experimental data
5. **Adjust** parameters manually based on discrepancies
6. **Repeat** steps 3-5 until satisfactory agreement

This iterative process requires deep domain expertise and can take **months to years** for complex materials — often described as a "tour de force" in the literature.

### MAIQMag Approach (ML-Accelerated)

Train neural networks on synthetic data to directly map observables to parameters:

```
Experimental Data  ─────►  Trained Encoder  ─────►  Hamiltonian Parameters
   (M(H), S(Q,ω))                                      (Ja, Jb, Jc, Dc)
                                                       + uncertainty estimates
```

**Goal:** 10× reduction in time-to-model for quantum magnetic materials.

**Key advantages:**
- No manual parameter tuning required
- Provides uncertainty quantification
- Can leverage multiple observables (multimodal)
- Works for materials outside training distribution (with appropriate UQ)

---

## 6. Connection to Real Experiments

### Magnetometry

| Technique | What it measures | Facilities |
|-----------|------------------|------------|
| SQUID magnetometry | DC magnetization vs field/temperature | Most university labs |
| VSM (Vibrating Sample) | AC/DC magnetization | National labs, universities |
| Pulsed-field magnetometry | High-field magnetization (to 100+ T) | NHMFL |

**VDP analog:** `mh_curve` artifacts simulate these measurements

### Neutron Scattering

| Technique | What it measures | Facilities |
|-----------|------------------|------------|
| Diffraction | Static magnetic structure | HFIR, SNS, NIST |
| Inelastic (INS) | Magnetic excitation spectrum S(Q,ω) | SNS (CNCS, ARCS), HFIR |
| Polarized neutrons | Spin-dependent scattering | SNS, NIST |

**VDP analog:** `ins_powder` artifacts simulate powder-averaged INS spectra

### Why Synthetic Data?

- **Volume:** 10,000 Hamiltonians with 110,000 artifacts — far more than experimentally accessible
- **Coverage:** Systematic sampling of parameter space via LHS
- **Labels:** Ground truth parameters known exactly (impossible for real materials)
- **Speed:** ML training requires large datasets; experiments are slow and expensive

---

## 7. ML Use Cases Enabled by VDP

### 7.1 Parameter Inference (Inverse Problem)

**Task:** Given M(H) curve → predict (Ja, Jb, Jc, Dc)

**Architecture:** Encoder network (CNN, Transformer, or MLP)

**Input:** Normalized magnetization curve (200 points)
**Output:** 4 Hamiltonian parameters + uncertainty

### 7.2 Multimodal Inference

**Task:** Given M(H) + S(Q,ω) → predict (Ja, Jb, Jc, Dc) with better accuracy

**Advantage:** Different observables constrain different parameter combinations; combining them reduces ambiguity

### 7.3 Physics-Conditional Training

**Task:** Train specialized models for specific physics regimes

**Examples:**
- Ferromagnetic materials only (Ja > 0)
- Easy-axis anisotropy only (Dc < 0)
- Frustrated systems (mixed-sign J values)

**VDP enables:** Server-side filtering before data transfer

### 7.4 Generative Models

**Task:** Learn the distribution of physically realistic M(H) curves

**Applications:**
- Data augmentation for rare physics regimes
- Anomaly detection (is this experimental curve physically plausible?)
- Interpolation in parameter space

---

## 8. Dataset Statistics

| Metric | Value |
|--------|-------|
| Total Hamiltonians | 10,000 |
| Total artifacts | ~110,000 |
| Artifacts per Hamiltonian | 11 (1 gs + 8 mh + 2 ins) |
| Total data size | ~111 GB |
| Storage format | HDF5 (one file per artifact) |
| Metadata format | Parquet manifests |

### Artifact Breakdown

| Type | Count | Description |
|------|-------|-------------|
| `mh_curve` | 80,000 | 4 directions × 2 field ranges × 10K Hamiltonians |
| `ins_powder` | 20,000 | 2 incident energies × 10K Hamiltonians |
| `gs_state` | 10,000 | 1 per Hamiltonian |

---

## 9. Two Access Modes for Different Workflows

### Mode A: Expert Path-Based Access

**Best for:** ML training pipelines, bulk data loading, maximum performance

```python
from query_manifest import query_manifest, load_from_manifest

# Query Tiled for filtered paths + physics parameters
manifest = query_manifest(client, axis="powder", Hmax_T=30, Ja_min=0)

# Load directly from HDF5 (no HTTP overhead)
X, Theta = load_from_manifest(manifest)
```

**Performance:** ~0.5s for 200 curves (matches Julia baseline)

### Mode B: Tiled Adapter Access

**Best for:** Interactive exploration, visualization, remote access

```python
# Access arrays via Tiled HTTP API
h = client["H_636ce3e4"]
mh_curve = h["mh_powder_30T"][:]  # Full array
ins_slice = h["ins_12meV"][100:200, 50:150]  # Partial read
```

**Performance:** Slower than Mode A but enables remote access and partial reads

---

## 10. References

- **Sunny.jl:** https://github.com/SunnySuite/Sunny.jl
- **MAIQMag Project:** Multimodal AI for 2D Quantum Magnets (DOE BES)
- **Spin wave theory:** Toth & Lake, J. Phys.: Condens. Matter 27, 166002 (2015)
- **PyChop:** https://github.com/mducle/pychop (neutron resolution modeling)

---

## 11. File Locations

| Resource | Path |
|----------|------|
| Generation script | `$VDP_DATA/generate_synthetic_lhs.jl` |
| HDF5 artifacts | `$VDP_DATA/data/schema_v1/artifacts/` |
| Parquet manifests | `$VDP_DATA/data/schema_v1/*.parquet` |
| Tiled catalog config | `$PROJ_VDP/tiled_poc/config.yml` |
| Demo notebooks | `$PROJ_VDP/tiled_poc/examples/` |

Where:
- `$VDP_DATA = /sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp`
- `$PROJ_VDP = /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp`
