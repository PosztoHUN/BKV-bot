let vonalak=[0,1,1,0,1,1,0,0,0,0,0,0,0];
// 70 72 73 74 75 76 77 78 79 80 81 82 83
let dSzam = Math.floor(Math.random() * 100);

let osszeg=0;

onload=function(){
    console.log("betöltve");
    potlas();
    grafikon();
}

function potlas(){
    for (let i = 0; i < vonalak.length; i++) {
        vonalak[i] = Math.floor(Math.random() * 10); // 0-9 közötti random szám
    }
}

let oszlopok = document.querySelectorAll(".oszlop");
console.log(oszlopok)

function grafikon(){
    console.log("kirajzolás");
    // A div méretét módosítjuk a mentes adott elemére. 20 sor

    for (i=0;i<vonalak.length;i++){
        //let arany = (200/dSzam.value)*10
        oszlopok[i].style.height=vonalak[i]*5+"px";
    }
}

// alapoz.onclick=function(){
//     vonalak=[0,0,0,0,0,0,0,0,0,0,0,0,0];
//     for (i=0;i<vonalak.length;i++){
//         oszlopok[i].style.height = 0 + "px"
//     }
// }