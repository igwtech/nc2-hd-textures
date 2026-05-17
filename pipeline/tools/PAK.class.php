<?php 

class PAK {
    const PAK_SIGNATURE0 = 0x3d458cde;
    const PAK_SIGNATURE1 = 0x883df70a;
    const PAK_SIGNATURE2 = 0x93847584;
    const PAK_SIGNATURE3 = 0xabfdefbd;
    const CHUNK = 1024;
    private $infile;
    private $inname;
    private $outfile;
    private $outname;
    private $outpath;

    public function decompressStream($instream,$outstream) {
        $this->infile=$instream;
        $this->outfile=$outstream;
        $first_long=$this->readLong();
        $this->logMessage("Detecting Signature: ". dechex($first_long));
        if($first_long == PAK::PAK_SIGNATURE1) {
            $uncompressed_size=$this->readNCSingleFile();
        }
        return $uncompressed_size;
    }

    public function compress($inputFilenameOrDir,$outputPath) {
        $this->logMessage("Compressing $inputFilenameOrDir into $outputPath");
        if(is_dir($inputFilenameOrDir)) {
            $this->logMessage("Opening Input Dir $inputFilenameOrDir");            
            $outname=basename($inputFilenameOrDir).".pak";
            $this->logMessage("Outpath $outname");
            $directory = new \RecursiveDirectoryIterator($inputFilenameOrDir,FilesystemIterator::SKIP_DOTS|FilesystemIterator::KEY_AS_PATHNAME|FilesystemIterator::CURRENT_AS_FILEINFO);            
            $iterator = new \RecursiveIteratorIterator($directory);
            $files = array();            
            $workPath = new SplFileInfo($inputFilenameOrDir);
            $this->outpath= $outputPath . DIRECTORY_SEPARATOR . $outname;
            $filenames=[];
            $files=[];
            $this->outfile = fopen($this->outpath,'wb');
            if(false === $this->outfile) {
                $this->endError("Unable to open output file {$this->outpath}");
            }
            foreach ($iterator as $k=>$fileinfo) {
                $k = str_replace($workPath->getRealPath(),"",$k);
                $k = str_replace($inputFilenameOrDir,"",$k);
                $k = ltrim($k,'/');
                $k = str_replace('/','\\',$k); // windows path
                print $k.PHP_EOL;                    
                $filenames[]=$k;
                $files[] = $fileinfo->getPathname();
            }
            $tmp = array_combine($files,$filenames);
            asort($tmp);
            $this->writeNCMultiFile(array_values($tmp),array_keys($tmp));
            fclose($this->outfile); $this->outfile=null;
          

        }else if (is_file($inputFilenameOrDir)) {
            $this->logMessage("Opening Input File $inputFilenameOrDir");            
            $this->infile=fopen($inputFilenameOrDir,'rb',false);
            if(!$this->infile) {
                $this->endError("Unable to open input file");
            }
            $this->inname = basename($inputFilenameOrDir);
            $this->outpath= realpath($outputPath);
            $this->logMessage("Outpath {$this->outpath}");


            fseek($this->infile,0,SEEK_END);
            $size = ftell($this->infile);
            fseek($this->infile,0,SEEK_SET);
            $compressed_size=$this->writeNCSingleFile($size);
            fclose($this->outfile); $this->outfile=null;
            $this->verify($this->outname, $compressed_size+16);
        }else{
            $this->logMessage("Error Input Dir $inputFilenameOrDir is not file or dir");
        }
    }
    public function decompress($filename,$path) {
        $this->logMessage("Opening Input File $filename");
        $this->logMessage("Outpath $path");
        $this->infile=fopen($filename,'rb',false);
        if(!$this->infile) {
            $this->endError("Unable to open input file");
        }
        $this->inname = basename($filename);
        $this->outpath=$path;

        fseek($this->infile,0,SEEK_END);
        $size = ftell($this->infile);
        fseek($this->infile,0,SEEK_SET);
        $first_long=$this->readLong();
        $this->logMessage("Detecting Signature: ". dechex($first_long));
        if($first_long == PAK::PAK_SIGNATURE0) {
            $this->readNCMultiFile();
            
        }else if($first_long == PAK::PAK_SIGNATURE1) {
            $uncompressed_size=$this->readNCSingleFile();
            fclose($this->outfile); $this->outfile=null;
            $this->verify($this->outname, $uncompressed_size);
        }else{
            // Unrecognized
            $this->endError("Unreconized file");
        }
    }
    private function verify($filename,$size) {
        // Verify
        if(filesize(realpath($filename)) == $size) {
            $this->logMessage("File $filename processed successfully");
            return true;
        }
        // else
        $this->logMessage("Size do not MATCH!!!");
        return false;        
    }

    public function deflate($finput,$foutput,$limit=PHP_INT_MAX) {
        $context= deflate_init(ZLIB_ENCODING_DEFLATE);
        $total_bytes=0;
        while(!feof($finput) && $limit>0 ) {
            $bytes=min($limit,PAK::CHUNK);
            $in_buffer = fread($finput,$bytes);
            if(false === $in_buffer) {
                $this->endError("Unable to read input bytes");
            }
            $limit -= $bytes;
            // echo "|".bin2hex($in_buffer)."|".PHP_EOL;
            $out_buffer=deflate_add($context,$in_buffer,(($bytes < PAK::CHUNK)? ZLIB_FINISH:ZLIB_NO_FLUSH));            
            $written=fwrite($foutput,$out_buffer);
            if(false === $written) {
                $this->endError("Unable to write output bytes");
            }
            $total_bytes+=$written;
        }
        return $total_bytes;
    }

    public function inflate($finput,$foutput,$limit=PHP_INT_MAX) {
        $context= inflate_init(ZLIB_ENCODING_DEFLATE);
        $total_bytes=0;
        while(!feof($finput) && $limit>0 ) {
            $bytes=min($limit,PAK::CHUNK);
            $in_buffer = fread($finput,$bytes);
            if(false === $in_buffer) {
                $this->endError("Unable to read input bytes");
            }
            $limit -= $bytes;
            // echo "|".bin2hex($in_buffer)."|".PHP_EOL;
            $out_buffer=inflate_add($context,$in_buffer);
            $written=fwrite($foutput,$out_buffer);
            if(false === $written) {
                $this->endError("Unable to write output bytes");
            }
            $total_bytes+=$written;
        }
        return $total_bytes;
    }
    private function readLong() {
        $buf=fread($this->infile,4);
        echo bin2hex($buf).PHP_EOL;
        $arr=unpack('V',$buf);        
        return $arr[1];
    }
    private function writeLong($value) {
        $buf=pack('V',$value);
        echo bin2hex($buf).PHP_EOL;
        return fwrite($this->outfile,$buf,4);
    }
    private function readDescriptor() {
        $buf=fread($this->infile,20);
        // echo bin2hex($buf).PHP_EOL;
        $arr = unpack('V5',$buf);
        // var_dump($arr);
        $fname=fread($this->infile,$arr[5]);
        return ['next'=>$arr[1],'offset'=>$arr[2],'compressed_size'=>$arr[3],'uncompressed_size'=>$arr[4],'name'=>trim($fname)];
    }
    private function writeDescriptor($desc) {
        $ret=0;
        $size = 21+strlen($desc['name']);
        $buf=pack('V5',$size ,$desc['offset'],$desc['compressed_size'],$desc['uncompressed_size'],strlen($desc['name'])+1) . $desc['name'];
        $ret+=fwrite($this->outfile,$buf);
        $ret+=fwrite($this->outfile,"\0");
        return $ret;
    }

    private function writeNCSingleFile($uncompressed_size) {
        
        $this->outname = realpath($this->outpath) . DIRECTORY_SEPARATOR . 'pak_'.$this->inname;
        if(!file_exists(dirname($this->outname))) {
            mkdir(dirname($this->outname),0777,true);
        }
        $this->logMessage("Output file: {$this->outname}");
        $this->outfile = fopen($this->outname,'wb',false);
        if(!$this->outfile) {
           $this->endError("Unable to open output file {$this->outname}");
        }

        $this->writeLong(PAK::PAK_SIGNATURE1);
        $this->writeLong(PAK::PAK_SIGNATURE2);
        $this->writeLong(PAK::PAK_SIGNATURE3);
        $this->logMessage("Uncompressed Size: $uncompressed_size");
        $this->writeLong($uncompressed_size);

        $compressed_size=$this->deflate($this->infile,$this->outfile,$uncompressed_size);
        $this->logMessage("Compressed Size: $compressed_size");
        return $compressed_size;
        
    }
    private function readNCSingleFile() {
        // NC single
        if($this->readLong() != PAK::PAK_SIGNATURE2) {
            $this->endError("Unreconized NC single file signature2");
        }

        if($this->readLong() != PAK::PAK_SIGNATURE3) {
            $this->endError("Unreconized NC single file signature3");
        }
        $this->logMessage("Neocron single file");
        $uncompressed_size = $this->readLong();
        $this->logMessage("Uncompressed Size: $uncompressed_size");
        $this->outname = $this->outpath . DIRECTORY_SEPARATOR . str_replace('pak_','',$this->inname);
        if(!file_exists(dirname($this->outname))) {
            mkdir(dirname($this->outname),0777,true);
        }
        $this->logMessage("Output file: {$this->outname}");
        $this->outfile = fopen($this->outname,'wb',false);
        if(!$this->outfile) {
           $this->endError("Unable to open output file {$this->outname}");
        }
        $this->inflate($this->infile,$this->outfile);
        $this->logMessage("Written Size: $uncompressed_size");
        return  $uncompressed_size;
        
    }
    private function writeNCMultiFile($filenames,$files) {
        $this->logMessage("Neocron multi file found");
        
        $estimate =4*2 +count($files)*20 /*bytes*/ +  array_reduce($filenames,function($e,$i) { return strlen($i)+1+$e;},0)  /* \0 terminator */;
        $this->logMessage("Header size $estimate");
        fwrite($this->outfile,str_repeat("\0",$estimate));
        rewind($this->outfile);
        $this->writeLong(PAK::PAK_SIGNATURE0);
        $this->writeLong(count($files));
        for($i=0;$i<count($files);$i++) {
            $this->logMessage("Writing file {$files[$i]}");
            $this->infile = fopen($files[$i],'rb');            
            $uncompressed_size =filesize($files[$i]);            
            $this->logMessage("Normal file {$uncompressed_size} uncompressed_size");
            $current_pos = ftell($this->outfile);
            $fname = $filenames[$i];
            $next = 4 /*bytes per int (32bit)*/ * 5 + strlen(trim($fname)) + 1 /* '\0' */;            
            $fp_mem = fopen('php://memory','wb');
            $compressed_size = $this->deflate($this->infile,$fp_mem,$uncompressed_size);
            $this->logMessage("Deflate file {$compressed_size} compressed_size");
            $desc = [
                'next'=>$next,
                'offset'=> $estimate,
                'compressed_size'=>$compressed_size,
                'uncompressed_size'=>$uncompressed_size,
                'name'=>trim($fname)
            ];
            $this->logMessage("... Write descriptor");
            $this->writeDescriptor($desc);
        
            $current_pos = ftell($this->outfile);
            fseek($this->outfile,$estimate,SEEK_SET);
            rewind($fp_mem);
            $this->logMessage("... Write data");
            fwrite($this->outfile,stream_get_contents($fp_mem));
            fclose($fp_mem);
            $estimate=ftell($this->outfile);
            fseek($this->outfile,$current_pos,SEEK_SET);
            fclose($this->infile); $this->infile=false;
        }
    }
    private function readNCMultiFile() {
        // NC multi            
        $this->logMessage("Neocron multi file found");
        $file_entries = $this->readLong();
        $descriptors=[];
        for($i=0;$i<$file_entries;$i++) {
            $desc=$this->readDescriptor();
            $this->logMessage($desc['name']);
            $descriptors[]=$desc;
        }

        foreach($descriptors as $i=>$desc) {
            // good place to do search
            $this->logMessage("Uncompressed Size: {$desc['uncompressed_size']}");
            $this->outname = $this->outpath . DIRECTORY_SEPARATOR . str_replace('\\',DIRECTORY_SEPARATOR, $desc['name']);
            $filedir=dirname($this->outname);
            if(!file_exists($filedir)) {
                $this->logMessage("Creating directory $filedir");
                mkdir($filedir,0777,true);
            }
            $this->logMessage("Output file: {$this->outname}");
            $this->outfile = fopen($this->outname,'wb',false);
            if(!$this->outfile) {
                $this->endError("Unable to open output file {$this->outname}");
            }
            fseek($this->infile,$desc['offset'],SEEK_SET);
            $this->inflate($this->infile,$this->outfile,$desc['compressed_size']);
            fclose($this->outfile); $this->outfile=null;
            $this->verify($this->outname, $desc['uncompressed_size']);
        }
    }
    public function __destruct()
    {
        if($this->infile) fclose($this->infile);
        if($this->outfile) fclose($this->outfile);
    }
    public function logMessage($message) {
        echo "[INFO] $message".PHP_EOL;
    }
    public function endError($message) {
        echo "[ERROR] $message".PHP_EOL;        
        exit(-1);
    }
}