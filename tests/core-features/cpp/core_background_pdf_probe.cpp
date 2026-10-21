// Direct Core metafile probe: no SDKJS and no browser/native JS changes.
#include <cstdint>
#include <fstream>
#include <string>
#include <vector>
struct Commands {
 std::vector<unsigned char> bytes;
 void byte(unsigned char v){bytes.push_back(v);}
 void integer(int32_t v){for(int i=0;i<4;++i)byte((uint32_t)v>>(i*8));}
 void number(double v){integer((int32_t)(v*100000));}
 void text(const std::string& value){integer((int32_t)value.size()*2);for(unsigned char c:value){byte(c);byte(0);}}
 void point(unsigned char command,double x,double y){byte(command);number(x);number(y);}
 void bounds(){byte(29);number(10);number(10);number(16.93333);number(12.7);}
 void enable(){byte(30);byte(1);}
 void rectangle(){byte(100);point(91,10,10);point(92,90,10);point(92,90,90);point(92,10,90);byte(97);byte(99);integer(256);byte(98);}
};
int main(int argc,char** argv){
 if(argc!=4)return 2;
 Commands c;c.byte(202);c.byte(200);c.number(100);c.byte(201);c.number(100);
 const std::string mode=argv[1];
 if(mode=="image") {c.byte(111);c.text(argv[2]);c.number(10);c.number(10);c.number(80);c.number(80);}
 else {
  c.byte(21);c.integer(3008);c.byte(32);c.text(argv[2]);c.byte(28);c.byte(1);c.byte(27);c.byte(255);
  if(mode=="bounds-first"){c.bounds();c.enable();}
  else if(mode=="enable-first"){c.enable();c.bounds();}
  c.rectangle();
 }
 c.byte(203);std::ofstream out(argv[3],std::ios::binary);out.write((const char*)c.bytes.data(),c.bytes.size());return out?0:3;
}
