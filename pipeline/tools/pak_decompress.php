<?php

include __DIR__ . '/PAK.class.php';

var_dump($argv[1]);
if(substr($argv[1],-4)==".pak") {
    // NC1 mode
    $path=__DIR__.'/tmp/'.substr($argv[1],0,-4).'/';
}else{
    // NC2 mode
    $path=__DIR__.'/tmp/'.dirname($argv[1]).'/';
}
if($argc > 2) {
    $path = $argv[2];
}
var_dump($path);

$obj = new PAK();
$obj->decompress($argv[1],$path);