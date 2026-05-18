<?php
include __DIR__ . '/PAK.class.php';
$obj = new PAK();
$path = $argv[2] ?? __DIR__.'/tmp/';
$obj->compress($argv[1],$path);