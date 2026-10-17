from . import ashby, generic_page, github_vagas, greenhouse, inhire, lever, linkedin, programathor, workable

# ATS com API JSON por slug (ordem usada ao sondar um nome de empresa)
ATS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workable": workable,
    "inhire": inhire,
}

# Fontes agregadoras (portais, busca pública e repositórios)
EXTRA_SOURCES = {
    "linkedin": linkedin,
    "github": github_vagas,
    "programathor": programathor,
    "generic": generic_page,
}


def fetch(ats: str, slug: str):
    if ats in EXTRA_SOURCES:
        return EXTRA_SOURCES[ats].fetch(slug)
    return ATS[ats].fetch(slug)
