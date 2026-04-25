export interface PaperInfo {
  title: string;
  authors: string;
  year: string;
  journal: string;
  pdfUrl: string;
  abstractUrl: string;
}

export const TOOL_PAPERS: Record<string, PaperInfo> = {
  immunebuilder: {
    title: "ImmuneBuilder: Deep-Learning models for predicting the structures of immune proteins",
    authors: "Abanades et al.",
    year: "2023",
    journal: "Communications Biology",
    pdfUrl: "/papers/immunebuilder/ImmuneBuilder.pdf",
    abstractUrl: "https://doi.org/10.1038/s42003-023-04927-7",
  },
  haddock3: {
    title: "HADDOCK3: A Modular and Versatile Platform for Integrative Modeling of Biomolecular Complexes",
    authors: "Giulini et al.",
    year: "2025",
    journal: "J. Chem. Inf. Model.",
    pdfUrl: "https://www.biorxiv.org/content/10.1101/2025.04.30.651432v1.full.pdf",
    abstractUrl: "https://doi.org/10.1021/acs.jcim.5c00969",
  },
  esmfold: {
    title: "Evolutionary-scale prediction of atomic-level protein structure with a language model",
    authors: "Lin et al.",
    year: "2023",
    journal: "Science",
    pdfUrl: "https://www.biorxiv.org/content/10.1101/2022.07.20.500902v2.full.pdf",
    abstractUrl: "https://doi.org/10.1126/science.ade2574",
  },
  alphafold_monomer: {
    title: "Highly accurate protein structure prediction with AlphaFold",
    authors: "Jumper et al.",
    year: "2021",
    journal: "Nature",
    pdfUrl: "https://pmc.ncbi.nlm.nih.gov/articles/PMC8371605/pdf/",
    abstractUrl: "https://doi.org/10.1038/s41586-021-03819-2",
  },
  rfdiffusion: {
    title: "De novo design of protein structure and function with RFdiffusion",
    authors: "Watson et al.",
    year: "2023",
    journal: "Nature",
    pdfUrl: "https://www.biorxiv.org/content/10.1101/2022.12.09.519842v2.full.pdf",
    abstractUrl: "https://doi.org/10.1038/s41586-023-06415-8",
  },
  proteinmpnn: {
    title: "Robust deep learning–based protein sequence design using ProteinMPNN",
    authors: "Dauparas et al.",
    year: "2022",
    journal: "Science",
    pdfUrl: "https://pmc.ncbi.nlm.nih.gov/articles/PMC9997061/pdf/",
    abstractUrl: "https://doi.org/10.1126/science.add2187",
  },
  abmap: {
    title: "Learning the language of antibody hypervariability",
    authors: "Singh et al.",
    year: "2025",
    journal: "PNAS",
    pdfUrl: "https://www.biorxiv.org/content/10.1101/2023.04.26.538476v2.full.pdf",
    abstractUrl: "https://doi.org/10.1073/pnas.2418918121",
  },
  equidock: {
    title: "Independent SE(3)-Equivariant Models for End-to-End Rigid Protein Docking",
    authors: "Ganea et al.",
    year: "2022",
    journal: "ICLR",
    pdfUrl: "https://arxiv.org/pdf/2111.07786",
    abstractUrl: "https://arxiv.org/abs/2111.07786",
  },
  ablang: {
    title: "AbLang: an antibody language model for completing antibody sequences",
    authors: "Olsen et al.",
    year: "2022",
    journal: "Bioinformatics Advances",
    pdfUrl: "https://academic.oup.com/bioinformaticsadvances/article-pdf/2/1/vbac046/45236785/vbac046.pdf",
    abstractUrl: "https://doi.org/10.1093/bioadv/vbac046",
  },
  biophi: {
    title: "BioPhi: A platform for antibody design, humanization, and humanness evaluation based on natural antibody repertoires and deep learning",
    authors: "Prihoda et al.",
    year: "2022",
    journal: "mAbs",
    pdfUrl: "/papers/biophi/BioPhi.pdf",
    abstractUrl: "https://doi.org/10.1080/19420862.2021.2020203",
  },
};
