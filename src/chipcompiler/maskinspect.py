"""Independent, read-only GDSII stream sanity checker and layer inventory.

This is NOT a design-rule checker or GDS layout viewer. It validates stream
record framing and key hierarchy markers to detect corrupt/misidentified files.
"""
from __future__ import annotations
import struct
from collections import Counter
from dataclasses import asdict,dataclass
from pathlib import Path

class GDSFormatError(ValueError):
    def __init__(self,code,message,offset=0):
        self.code=code;self.offset=offset
        super().__init__(message)

@dataclass
class GDSInspection:
    file:str
    bytes:int
    library:str|None
    structures:list[str]
    layer_elements:dict[int,int]
    elements:int
    records:int
    status:str='STRUCTURALLY_READABLE_NOT_PHYSICALLY_VERIFIED'
    def as_dict(self):return asdict(self)

def inspect_gds(path:Path,max_records:int=10_000_000,max_structures:int=250_000)->GDSInspection:
    path=Path(path).resolve()
    size=path.stat().st_size
    if size<8:raise GDSFormatError('GDS.TOO_SMALL','File too short to contain a GDSII stream')
    library=None;structures=[];layers=Counter();current_layer=None
    in_library=False;in_structure=False;in_element=False;records=0;elements=0;endlib=False
    with path.open('rb') as stream:
        while stream.tell()<size:
            offset=stream.tell()
            hdr=stream.read(4)
            if len(hdr)!=4:raise GDSFormatError('GDS.TRUNCATED','Incomplete record header',offset)
            length,record_type,datatype=struct.unpack('>HBB',hdr)
            if length<4 or length%2 or length>size-offset:
                raise GDSFormatError('GDS.BAD_RECORD_LENGTH',f'Illegal record length {length}',offset)
            data=stream.read(length-4)
            if len(data)!=length-4:raise GDSFormatError('GDS.TRUNCATED','Incomplete record payload',offset)
            records+=1
            if records>max_records:
                raise GDSFormatError('GDS.RECORD_LIMIT','GDS record limit exceeded; use a dedicated EDA layout viewer',offset)
            if records==1 and (record_type,datatype)!=(0,2):
                raise GDSFormatError('GDS.HEADER','First record must be a GDSII HEADER (type 0, datatype 2)',offset)
            if record_type==1:  # BGNLIB
                if in_library:raise GDSFormatError('GDS.NESTED_LIBRARY','Nested library declaration',offset)
                in_library=True
            elif record_type==2:  # LIBNAME
                library=data.rstrip(b'\0').decode('ascii','replace')
            elif record_type==5:  # BGNSTR
                if not in_library or in_structure:raise GDSFormatError('GDS.STRUCTURE_ORDER','Bad BGNSTR placement',offset)
                in_structure=True
                current_layer=None
            elif record_type==6:  # STRNAME
                if not in_structure:raise GDSFormatError('GDS.STRUCTURE_NAME','STRNAME outside structure',offset)
                structures.append(data.rstrip(b'\0').decode('ascii','replace'))
                if len(structures)>max_structures:raise GDSFormatError('GDS.STRUCTURE_LIMIT','Structure-count limit exceeded',offset)
            elif record_type==7:  # ENDSTR
                if not in_structure or in_element:raise GDSFormatError('GDS.ENDSTR','Unbalanced structure/element',offset)
                in_structure=False
            elif record_type in (8,9,10,11,12,21,45,46):  # boundary,path,sref,aref,text,node,box etc
                if not in_structure or in_element:
                    raise GDSFormatError('GDS.ELEMENT_ORDER','Unexpected or nested element',offset)
                in_element=True;current_layer=None
            elif record_type==13:  # LAYER
                if len(data)!=2 or not in_element:raise GDSFormatError('GDS.LAYER','Invalid LAYER record',offset)
                current_layer=struct.unpack('>H',data)[0]
            elif record_type==17:  # ENDEL
                if not in_element:raise GDSFormatError('GDS.ENDEL','Unexpected ENDEL',offset)
                in_element=False;elements+=1
                if current_layer is not None:layers[current_layer]+=1
            elif record_type==4:  # ENDLIB
                if not in_library or in_structure or in_element:
                    raise GDSFormatError('GDS.ENDLIB','Unbalanced ENDLIB',offset)
                if stream.tell()!=size:raise GDSFormatError('GDS.TRAILING','Data follows ENDLIB',stream.tell())
                endlib=True;break
    if not endlib or library is None:
        raise GDSFormatError('GDS.INCOMPLETE','Missing LIBNAME or ENDLIB',size)
    return GDSInspection(str(path),size,library,structures,dict(sorted(layers.items())),elements,records)
