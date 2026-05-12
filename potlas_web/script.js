let potlasok = {};

async function loadPotlasok() {

    const response = await fetch("potlasok.json");

    potlasok = await response.json();

    console.log(potlasok);

    updateStats();
}

function updateStats() {

    const lines = Object.keys(potlasok);

    const oszlopok = document.querySelectorAll(".oszlop");

    lines.forEach((line, index) => {

        const value = potlasok[line];

        const magassag = value * 20;

        oszlopok[index].style.height = `${magassag}px`;
    });
}

loadPotlasok();

setInterval(loadPotlasok, 10000);