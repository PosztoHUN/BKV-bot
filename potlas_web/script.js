let vonalak=[0,1,1,0,1,1,0,0,0,0,0,0,0];
// 70 72 73 74 75 76 77 78 79 80 81 82 83
let dSzam

let osszeg=0;

potlas
grafikon

function potlas(){
    //véletlenszám
    let veletlen1=Math.floor(Math.random()*6)+1;
    //képnév összerakása
    let kepnev1="kepek/k"+veletlen1+".png";
    //kiíratás konzolra
    console.log(kepnev1);
    //kiíratás a kép helyére
    kep1.src=kepnev1;
    let veletlen2=Math.floor(Math.random()*6)+1;
    //képnév összerakása
    let kepnev2="kepek/k"+veletlen2+".png";
    //kiíratás konzolra
    console.log(kepnev2);
    //kiíratás a kép helyére
    kep2.src=kepnev2;
 
    osszeg=veletlen1+veletlen2;
    eredmeny.innerHTML="Összesen:"+osszeg; 
}

let oszlopok = document.querySelectorAll(".oszlop");
console.log(oszlopok)

function grafikon(){
    console.log("kirajzolás");
    // A div méretét módosítjuk a mentes adott elemére. 20 sor

    for (i=0;i<vonalak.length;i++){
        let arany = (200/dSzam.value)*3
        oszlopok[i].style.height=vonalak[i]*arany+"px";
    }
}

// alapoz.onclick=function(){
//     vonalak=[0,0,0,0,0,0,0,0,0,0,0,0,0];
//     for (i=0;i<vonalak.length;i++){
//         oszlopok[i].style.height = 0 + "px"
//     }
// }