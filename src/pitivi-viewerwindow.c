/* 
 * PiTiVi
 * Copyright (C) <2004> Edward G. Hervey <hervey_e@epita.fr>
 *                      Guillaume Casanova <casano_g@epita.fr>
 *
 * This software has been written in EPITECH <http://www.epitech.net>
 * EPITECH is a computer science school in Paris - FRANCE -
 * under the direction of Flavien Astraud and Jerome Landrieu.
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public
 * License along with this program; if not, write to the
 * Free Software Foundation, Inc., 59 Temple Place - Suite 330,
 * Boston, MA 02111-1307, USA.
 */

#include "pitivi.h"
#include "pitivi-viewerwindow.h"

#include <glib.h>
#include <gtk/gtk.h>
#include <gst/gst.h>
#include <gdk/gdkx.h>
#include <gst/xoverlay/xoverlay.h>
#include <gst/play/play.h>

static     PitiviProjectWindowsClass *parent_class;

enum {
  PLAY,
  PAUSE,
  STOP
};

struct _PitiviViewerWindowPrivate
{
  gboolean	dispose_has_run;

  /* instance private members */

  gchar		*location;
  gboolean	play_status;
  
  GstElement	*pipe;
  GstElement	*bin_src;
  GstElement	*sink;
  GstElement	*spider;
  
  GtkWidget	*main_vbox;
  GtkWidget	*toolbar; 
  GtkWidget	*button_play;
  GtkWidget	*button_stop;
  GtkWidget	*button_backward;
  GtkWidget	*button_forward;
  GtkWidget	*video_area;

};

/*
 * forward definitions
 */

void	video_play(GtkWidget *widget, gpointer data)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) data;

  if (self->private->play_status == PLAY) {
    g_print ("[CallBack]:video_pause\n");
    self->private->play_status = PAUSE;
  } else if (self->private->play_status == PAUSE) {
    g_print ("[CallBack]:video_play\n");
    self->private->play_status = PLAY;
  } else if (self->private->play_status == STOP) {
    g_print ("[CallBack]:video_play\n");
    self->private->play_status = PLAY;
  }
  return ;
}

void	video_stop(GtkWidget *widget, gpointer data)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) data;

  g_print ("[CallBack]:video_stop\n");
  self->private->play_status = STOP;
  return ;
}

void	video_backward(GtkWidget *widget, gpointer data)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) data;

  g_print ("[CallBack]:video_backward\n");
  return ;
}

void	video_forward(GtkWidget *widget, gpointer data)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) data;

  g_print ("[CallBack]:video_forward\n");
  return ;
}

GtkWidget *
get_image (gpointer data, char **im_name)
{
  GtkWidget	* win;
  GdkColormap	*colormap;
  GdkBitmap	*mask;
  GdkPixmap	*pixmap;
  GtkWidget	*pixmapw;

  win = (GtkWidget *) data;
  colormap = gtk_widget_get_colormap (win);
  pixmap = gdk_pixmap_colormap_create_from_xpm_d (win->window, 
						  colormap, 
						  &mask, 
						  NULL,
						  im_name);
  pixmapw = gtk_image_new_from_pixmap (pixmap, mask);

  return pixmapw;
}  

void
create_gui (gpointer data)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) data;
  GtkWidget	*image;

  // main Vbox
  self->private->main_vbox = gtk_vbox_new (FALSE, FALSE);
  gtk_container_add (GTK_CONTAINER (self), self->private->main_vbox);

  // Create Video Display (Drawing Area)
  self->private->video_area = gtk_drawing_area_new ();
  //gtk_widget_set_size_request (self->private->video_area, 320, 240);
  gtk_box_pack_start (GTK_BOX (self->private->main_vbox), self->private->video_area, TRUE, TRUE, 0);

  // Create hbox for toolbar
  self->private->toolbar = gtk_hbox_new (FALSE, FALSE);
  gtk_box_pack_start (GTK_BOX (self->private->main_vbox), self->private->toolbar, FALSE, TRUE, 0);
  
  // Buttons for Toolbar

  // Button Backward
  image = get_image (self, backward_xpm);
  self->private->button_backward = gtk_button_new ();
  gtk_container_add (GTK_CONTAINER (self->private->button_backward), image);
  gtk_widget_set_size_request (GTK_WIDGET (self->private->button_backward), 30, 17);
  gtk_signal_connect (GTK_OBJECT (self->private->button_backward), "pressed", 
                      GTK_SIGNAL_FUNC (video_backward), self);
  gtk_box_pack_start (GTK_BOX (self->private->toolbar), 
		      self->private->button_backward, FALSE, FALSE, 0);

  // Button Play
  image = get_image (self, play_xpm);
  self->private->button_play = gtk_button_new ();
  gtk_container_add (GTK_CONTAINER (self->private->button_play), image);
  gtk_signal_connect (GTK_OBJECT (self->private->button_play), "clicked", 
                      GTK_SIGNAL_FUNC (video_play), self);
  gtk_box_pack_start (GTK_BOX (self->private->toolbar), self->private->button_play, FALSE, FALSE, 0);
  gtk_widget_set_size_request (self->private->button_play, 60, 17);
 
  // Button Forward
  image = get_image (self, forward_xpm);
  self->private->button_forward = gtk_button_new ();
  gtk_container_add (GTK_CONTAINER (self->private->button_forward), image);
  gtk_widget_set_size_request (GTK_WIDGET (self->private->button_forward), 30, 17);
  gtk_signal_connect (GTK_OBJECT (self->private->button_forward), "pressed", 
                      GTK_SIGNAL_FUNC (video_forward), self);
  gtk_box_pack_start (GTK_BOX (self->private->toolbar),
		      self->private->button_forward, FALSE, TRUE, 0);

  // Button Stop
  image = get_image (self, stop_xpm);
  self->private->button_stop = gtk_button_new ();
  gtk_container_add (GTK_CONTAINER (self->private->button_stop), image);
  gtk_widget_set_size_request (GTK_WIDGET (self->private->button_stop), 30, 17);
  gtk_signal_connect (GTK_OBJECT (self->private->button_stop), "clicked", 
                      GTK_SIGNAL_FUNC (video_stop), self);
  gtk_box_pack_start (GTK_BOX (self->private->toolbar),
		      self->private->button_stop, FALSE, TRUE, 0);
 
  return;
}

void
create_stream (gpointer data)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) data;

  self->private->pipe = gst_pipeline_new ("pipeline");
  g_assert (self->private->pipe != NULL);

  self->private->bin_src = gst_element_factory_make ("videotestsrc", "video_source");
  g_assert (self->private->bin_src != NULL);

  self->private->sink = gst_element_factory_make ("xvimagesink", "video_display");
  g_assert (self->private->sink != NULL);

  gst_bin_add_many (GST_BIN (self->private->pipe),
		    self->private->bin_src,
		    self->private->sink,
		    NULL);

  if (!gst_element_link (self->private->bin_src, self->private->sink)) 
    printf ("could not link elem\n");

  
  gst_element_set_state (self->private->pipe, GST_STATE_PLAYING);
  self->private->play_status = PLAY;

  return ;
}

gboolean	idle_func_video (gpointer data)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) data;

  if ( gst_element_get_state (self->private->pipe) == GST_STATE_PLAYING ) {
    gst_x_overlay_set_xwindow_id 
      ( GST_X_OVERLAY ( self->private->sink ), 
	GDK_WINDOW_XWINDOW ( self->private->video_area->window ) );
    gst_bin_iterate (GST_BIN (self->private->pipe));
  }
  return TRUE;
}

/*
 * Insert "added-value" functions here
 */

PitiviViewerWindow *
pitivi_viewerwindow_new(PitiviMainApp *mainapp, PitiviProject *project)
{
  PitiviViewerWindow	*viewerwindow;

  //g_print ("coucou:new\n");
  viewerwindow = (PitiviViewerWindow *) g_object_new(PITIVI_VIEWERWINDOW_TYPE, 
						     "mainapp", mainapp,
						     "project", project, NULL);
  g_assert(viewerwindow != NULL);
  return viewerwindow;
}

static GObject *
pitivi_viewerwindow_constructor (GType type,
				 guint n_construct_properties,
				 GObjectConstructParam * construct_properties)
{
  //g_print ("coucou:constructor\n");

  GObject *obj;
  {
    obj = G_OBJECT_CLASS (parent_class)->constructor (type, n_construct_properties,
						      construct_properties);
  }

  return obj;
}

static void
pitivi_viewerwindow_instance_init (GTypeInstance * instance, gpointer g_class)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) instance;

  self->private = g_new0(PitiviViewerWindowPrivate, 1);
  
  /* initialize all public and private members to reasonable default values. */ 
  
  self->private->dispose_has_run = FALSE;

  gtk_window_set_default_size(GTK_WINDOW(self), 300, 200);
  
  /* initialize all public and private members to reasonable default values. */ 
  
  self->private->location = "";
  create_gui (self);
  create_stream (self);
  g_idle_add (idle_func_video, self);
}

static void
pitivi_viewerwindow_dispose (GObject *object)
{
  PitiviViewerWindow	*self = PITIVI_VIEWERWINDOW(object);

  /* If dispose did already run, return. */
  if (self->private->dispose_has_run)
    return;
  
  /* Make sure dispose does not run twice. */
  self->private->dispose_has_run = TRUE;

	
  g_idle_remove_by_data (self);


  /* 
   * In dispose, you are supposed to free all types referenced from this 
   * object which might themselves hold a reference to self. Generally, 
   * the most simple solution is to unref all members on which you own a 
   * reference. 
   */

  G_OBJECT_CLASS (parent_class)->dispose (object);
}

static void
pitivi_viewerwindow_finalize (GObject *object)
{
  PitiviViewerWindow	*self = PITIVI_VIEWERWINDOW(object);

  /* 
   * Here, complete object destruction. 
   * You might not need to do much... 
   */

  g_free (self->private);
  G_OBJECT_CLASS (parent_class)->finalize (object);
}

static void
pitivi_viewerwindow_set_property (GObject * object,
			      guint property_id,
			      const GValue * value, GParamSpec * pspec)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) object;

  switch (property_id)
    {
      /*   case PITIVI_VIEWERWINDOW_PROPERTY: { */
      /*     g_free (self->private->name); */
      /*     self->private->name = g_value_dup_string (value); */
      /*     g_print ("maman: %s\n",self->private->name); */
      /*   } */
      /*     break; */
    default:
      /* We don't have any other property... */
      g_assert (FALSE);
      break;
    }
}

static void
pitivi_viewerwindow_get_property (GObject * object,
			      guint property_id,
			      GValue * value, GParamSpec * pspec)
{
  PitiviViewerWindow *self = (PitiviViewerWindow *) object;

  switch (property_id)
    {
      /*  case PITIVI_VIEWERWINDOW_PROPERTY: { */
      /*     g_value_set_string (value, self->private->name); */
      /*   } */
      /*     break; */
    default:
      /* We don't have any other property... */
      g_assert (FALSE);
      break;
    }
}

static void
pitivi_viewerwindow_class_init (gpointer g_class, gpointer g_class_data)
{
  GObjectClass *gobject_class = G_OBJECT_CLASS (g_class);
  PitiviViewerWindowClass *klass = PITIVI_VIEWERWINDOW_CLASS (g_class);

  parent_class = g_type_class_peek_parent (g_class);

  gobject_class->constructor = pitivi_viewerwindow_constructor;
  gobject_class->dispose = pitivi_viewerwindow_dispose;
  gobject_class->finalize = pitivi_viewerwindow_finalize;

  gobject_class->set_property = pitivi_viewerwindow_set_property;
  gobject_class->get_property = pitivi_viewerwindow_get_property;

  /* Install the properties in the class here ! */
  /*   pspec = g_param_spec_string ("maman-name", */
  /*                                "Maman construct prop", */
  /*                                "Set maman's name", */
  /*                                "no-name-set" /\* default value *\/, */
  /*                                G_PARAM_CONSTRUCT_ONLY | G_PARAM_READWRITE); */
  /*   g_object_class_install_property (gobject_class, */
  /*                                    MAMAN_BAR_CONSTRUCT_NAME, */
  /*                                    pspec); */


}

GType
pitivi_viewerwindow_get_type (void)
{
  static GType type = 0;
 
  if (type == 0)
    {
      static const GTypeInfo info = {
	sizeof (PitiviViewerWindowClass),
	NULL,			/* base_init */
	NULL,			/* base_finalize */
	pitivi_viewerwindow_class_init,	/* class_init */
	NULL,			/* class_finalize */
	NULL,			/* class_data */
	sizeof (PitiviViewerWindow),
	0,			/* n_preallocs */
	pitivi_viewerwindow_instance_init	/* instance_init */
      };
      type = g_type_register_static (PITIVI_PROJECTWINDOWS_TYPE,
				     "PitiviViewerWindowType", &info, 0);
    }

  return type;
}
