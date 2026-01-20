function OpenGlobalPopup(url,width,height,name,fullscreen)
{
    //trato de llamar al constructor
    try
    {
        var ObjPopup = new top.GlobalPopUpHandler(name,openPopUp(url,width,height,name,fullscreen)) ;
        ObjPopup.setHandler()
        
        objHand = ObjPopup.getHandler();
        objHand.focus();
        return  ObjPopup;    
         
    }
    catch(ex)
    {
        try
        {
            var ObjPopup = new GlobalPopUpHandler(name,openPopUp(url,width,height,name,fullscreen)) ;
            objHand = ObjPopup.getHandler();
            objHand.focus();
            return  ObjPopup;    
         }
         catch(ex){openPopUp(url,width,height,name,fullscreen)}
        
    }
}

function CloseGlobalPopup(name)
{
    
    var ObjPopup = new top.GlobalPopUpHandler(name,null) ;
    ObjPopup.closePopUp()
    return ;     
    
}

/*
    CREATED BY:     Agustín SERRA
    CREATION DATE:  07/09/2007
    DESCRIPTION:    Permite la apertura de PopUps con parámetros opcionales.
*/
function openPopUp (url)
{
    
    var arg1 = openPopUp.arguments[1] || 800;
    var arg2 = openPopUp.arguments[2] || 520;
    var arg3 = openPopUp.arguments[3] || null;
    var arg4 = openPopUp.arguments[4] || 0;

    var width           = (arg1 != 0    && arg1 != null && arg1 != '')  ? arg1 : 800; //530;
    var height          = (arg2 != 0    && arg2 != null && arg2 != '')  ? arg2 : 520; //300;
    var title           = (arg3 != 0    && arg3 != '')                  ? arg3 : null;
    var fullscreen      = (arg4 != null && arg4 != '')                  ? arg4 : 0;

    var leftposition    = 0;
    var topposition     = 0;

    if (fullscreen == 1) {
        width = screen.width;
        height = screen.height;
    } else {
        leftposition = (screen.width) ? (screen.width - width) / 2 : 0;
        topposition = (screen.height) ? (screen.height - height) / 2 : 0;
    }

    var style = 'width = ' + width + ', height = ' + height + ', ' +
                'top = ' + topposition + ' , left = ' + leftposition + ', ' +
                'menubar = no, toolbar = no, ' +
                'status = yes, location = no, ' +
                'scrollbars = yes, resizable = yes';

    
   
    
    return window.open(url, title, style);
     
}

function openPopUpTitle (url, titulo)
{
    
    var arg1 = openPopUpTitle.arguments[1] || 800;
    var arg2 = openPopUpTitle.arguments[2] || 520;
    var arg3 = openPopUpTitle.arguments[3] || null;
    var arg4 = openPopUpTitle.arguments[4] || 0;

    var width           = (arg1 != 0    && arg1 != null && arg1 != '')  ? arg1 : 800; //530;
    var height          = (arg2 != 0    && arg2 != null && arg2 != '')  ? arg2 : 520; //300;
    var title           = (arg3 != 0    && arg3 != '')                  ? arg3 : null;
    var fullscreen      = (arg4 != null && arg4 != '')                  ? arg4 : 0;

    var leftposition    = 0;
    var topposition     = 0;

    if (fullscreen == 1) {
        width = screen.width;
        height = screen.height;
    } else {
        leftposition = (screen.width) ? (screen.width - width) / 2 : 0;
        topposition = (screen.height) ? (screen.height - height) / 2 : 0;
    }

    var style = 'width = ' + width + ', height = ' + height + ', ' +
                'top = ' + topposition + ' , left = ' + leftposition + ', ' +
                'menubar = no, toolbar = no, ' +
                'status = yes, location = no, ' +
                'scrollbars = yes, resizable = yes';

    
   
    
    return window.open(url, titulo, style);
     
}

/*
    CREATED BY:     Agustín SERRA
    CREATION DATE:  30/10/2007
    DESCRIPTION:    Permite cancelar las teclas que se oprimen en un control por medio de su código.
                    Por ejemplo: cancelPressEnter(event, 13) no permite que se oprima Enter.
*/
function cancelKeysPress(e)
{
    var keynum;
    var resp = true;

    if(window.event) // IE
    {
        keynum = e.keyCode;
    }
    else if(e.which) // Netscape/Firefox/Opera
    {
        keynum = e.which;
    }

    
    for (var key = 1 ; key < cancelKeysPress.arguments.length ; key++)
    {
        if(keynum == cancelKeysPress.arguments[key]) resp = false;
    }
    
    return resp;
}

function validateAmount(source, arguments)
{
	var numAux;
    var decimales = new Array();
	
	//separa decimales
	decimales=arguments.Value.split(dec);
	
	//si tiene mas de un separador decimal, entonces es incorrecto
	if (decimales.length>2)
	{
		arguments.IsValid = false;
		return;
	}
	else
	{
		if (decimales.length==2)
		{
			//verifica que la parte decimal sea numérica
			numAux=parseInt(decimales[1]);
			if (numAux=='NaN' || numAux!=decimales[1])
			{
				arguments.IsValid =  false;
				return;
			}
		}
	}
	
	var miles=new Array();
	miles=decimales[0].split(thousand);
	
	switch (miles.length)
	{
		case 0:
			arguments.IsValid =  false;
			return;
		case 1:
			numAux=parseInt(miles[0]);
			if (numAux=='NaN' || numAux!=miles[0])
			{
				arguments.IsValid =  false;
				return;
			}
			break;
		default:
			for (i=0; i<miles.length;i++)
			{
				numAux=parseInt(miles[i]);
				if (numAux=='NaN' || numAux!=miles[i])
				{
					//no es número
					arguments.IsValid =  false;
					return;
				}
				else
				{
					if (miles[i].length!=3)
					{
						if (i==0)
						{
							if (miles[i].length>3)
							{
								arguments.IsValid =  false;
								return;
							}
						}
						else
						{
							arguments.IsValid =  false;
							return;
						}
					}
				}
			}
			break;
	}

	arguments.IsValid =  true;
}
/*
Asignado Por: Patricio Milan
Realizado Por: Javier Borrás
Fecha: 11/02/2008
Funcionalidad del tooltip personalizable
-> para implementar se debe agregar el siguiente código en
el body de la página:
<span id="toolTipBox" width="200"></span> 
Y en el control que se quiera utilizar el tooltip:
onMouseOver="toolTip('Texto en Formato HTML que se va a mostrar',this)"
*/

function toolTip(text,me) { 
       theObj=me; 
       theObj.onmousemove=updatePos; 
       document.getElementById('toolTipBox').innerHTML=text; 
       document.getElementById('toolTipBox').style.display="block"; 
       window.onscroll=updatePos; 
} 
function updatePos() { 
       var ev=arguments[0]?arguments[0]:event; 
       var x=ev.clientX; 
       var y=ev.clientY; 
       diffX=24; 
       diffY=0; 
       document.getElementById('toolTipBox').style.top  = y-2+diffY+document.body.scrollTop+ "px"; 
       document.getElementById('toolTipBox').style.left = x-2+diffX+document.body.scrollLeft+"px"; 
       theObj.onmouseout=hideMe; 
} 
  
function hideMe() { 
       document.getElementById('toolTipBox').style.display="none";
   }


function validateMaxlength(textareaControl, maxlength) {

   if (document.getElementById(textareaControl).value.length > maxlength - 1) {
        document.getElementById(textareaControl).value = document.getElementById(textareaControl).value.substring(0, maxlength - 1);
        alert("Debe ingresar hasta un maximo de "+maxlength+" caracteres");
   }
}


function lstInvitedProviders_DoubleClick() {

    document.forms[0].lstInvitedProvidersHidden.value = "doubleclicked";
    document.forms[0].submit();
}

//ProcurementRevocar.aspx
function funLoadAttach() {
    if (document.getElementById('fupAttachment').value == '') {
        alert('Sin adjunto seleccionado');
        return false;

    } else {
        __doPostBack('btnAdjuntos', '')
        return;

    }

}

function suspenderLicitacion(Aviso) {
    if (confirm(Aviso)) {
        return true;
    } else {
        return false;
    }
}


function revocarLicitacion(Aviso) {
    if (confirm(Aviso)) {
        return true;
    } else {
        return false;
    }
}

function validateNumeric(source, arguments) {
    debugger;
    if (!/^\d+$/.test(arguments.Value)) {
        arguments.IsValid = false;
    } else {
        arguments.IsValid = true;
    }
}

