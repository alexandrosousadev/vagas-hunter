from . import (
    apinfo,
    ashby,
    catho,
    eudev,
    geekhunter,
    generic_page,
    github_vagas,
    greenhouse,
    gupy,
    infojobs,
    inhire,
    jobicy,
    jobs99,
    lever,
    linkedin,
    mosyle,
    nerdin,
    posts_web,
    programathor,
    recrutei,
    remotive,
    solides,
    vagascom,
    workable,
)

# ATS com API JSON por slug (ordem usada ao sondar um nome de empresa)
ATS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workable": workable,
    "inhire": inhire,
}

# Fontes agregadoras (portais, busca pública, posts de feed e repositórios)
EXTRA_SOURCES = {
    "linkedin": linkedin,
    "gupy": gupy,
    "catho": catho,
    "eudev": eudev,
    "posts": posts_web,
    "vagascom": vagascom,
    "jobicy": jobicy,
    "remotive": remotive,
    "github": github_vagas,
    "programathor": programathor,
    "generic": generic_page,
    "mosyle": mosyle,
    "solides": solides,
    "nerdin": nerdin,
    "recrutei": recrutei,
    "apinfo": apinfo,
    "infojobs": infojobs,
    "geekhunter": geekhunter,
    "99jobs": jobs99,
}


def fetch(ats: str, slug: str):
    if ats in EXTRA_SOURCES:
        return EXTRA_SOURCES[ats].fetch(slug)
    return ATS[ats].fetch(slug)
