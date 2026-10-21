// Links the production path geometry; includes the production clipping block.
#include "GraphicsPath.h"
#include "BooleanOperations.h"
#include <cassert>
#include <cmath>
#include <iostream>
void check(bool isStretch,bool bIsEnableBrushRect,double bx,double by,double bw,double bh,double expectedW,double expectedH){
 Aggplus::CGraphicsPath drawPath,path,clipPath;
 drawPath.AddRectangle(10,10,80,80);
 Aggplus::RectF_T<double> clipRect(bx,by,bw,bh);
 #include "tile_clip_body.inc"
 double x,y,w,h;path.GetBounds(x,y,w,h);
 assert(std::fabs(w-expectedW)<1e-6);assert(std::fabs(h-expectedH)<1e-6);
}
int main(){
 check(false,false,0,0,0,0,80,80);
 check(false,true,10,10,16,12,80,80);
 check(true,false,0,0,0,0,80,80);
 check(true,true,10,10,16,12,16,12);
 std::cout<<"PASS: tile/default/stretch path coverage\n";
}
