.class public final synthetic Lvr9;
.super Ljava/lang/Object;
.source "SourceFile"

# interfaces
.implements Lbb8;


# instance fields
.field public final synthetic E:I


# direct methods
.method public synthetic constructor <init>(I)V
    .locals 0

    iput p1, p0, Lvr9;->E:I

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method


# virtual methods
.method public final invoke(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;
    .locals 19

    move-object/from16 v0, p0

    iget v0, v0, Lvr9;->E:I

    const-class v1, Lmi6;

    const-class v2, Lou9;

    const-class v3, Loxc;

    const/4 v4, 0x0

    const-class v5, Lhse;

    const-class v6, Lnta;

    const/4 v7, 0x1

    const-class v8, Ljava/lang/String;

    const-class v9, Lzf0;

    const/4 v10, 0x0

    packed-switch v0, :pswitch_data_0

    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v1, Lqn5;

    invoke-static {v0}, Lnk9;->f(Ly1g;)Landroid/content/Context;

    move-result-object v2

    sget-object v3, Lp2f;->a:Lq2f;

    const-class v4, Lac6;

    invoke-virtual {v3, v4}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v4

    invoke-virtual {v0, v4, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v4

    check-cast v4, Lac6;

    invoke-virtual {v4}, Lac6;->a()Ljava/lang/String;

    move-result-object v4

    invoke-virtual {v3, v6}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v6

    invoke-virtual {v0, v6, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v6

    check-cast v6, Lnta;

    invoke-virtual {v3, v5}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v3

    invoke-virtual {v0, v3, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lhse;

    invoke-direct {v1, v2, v4, v6, v0}, Lqn5;-><init>(Landroid/content/Context;Ljava/lang/String;Lnta;Lhse;)V

    return-object v1

    :pswitch_0
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v1, Lp2f;->a:Lq2f;

    invoke-virtual {v1, v9}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lzf0;

    instance-of v1, v0, Lxf0;

    if-eqz v1, :cond_0

    const-string v10, "https://sandbox.claudemcpcontent.com/mcp_apps"

    goto :goto_2

    :cond_0
    instance-of v1, v0, Lyf0;

    if-nez v1, :cond_4

    instance-of v1, v0, Lvf0;

    if-eqz v1, :cond_1

    goto :goto_1

    :cond_1
    instance-of v1, v0, Lwf0;

    if-nez v1, :cond_3

    instance-of v0, v0, Luf0;

    if-eqz v0, :cond_2

    goto :goto_0

    :cond_2
    invoke-static {}, Lla7;->d()V

    goto :goto_2

    :cond_3
    :goto_0
    const-string v10, "http://localhost:4010/mcp_apps"

    goto :goto_2

    :cond_4
    :goto_1
    const-string v10, "https://staging.claudemcpcontent.com/mcp_apps"

    :goto_2
    return-object v10

    :pswitch_1
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v1, Lp2f;->a:Lq2f;

    invoke-virtual {v1, v9}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lzf0;

    instance-of v0, v0, Lxf0;

    if-eqz v0, :cond_5

    const-string v0, "https://jishnupg-hermes.hf.space"

    goto :goto_3

    :cond_5
    const-string v0, "https://jishnupg-hermes.hf.space"

    :goto_3
    return-object v0

    :pswitch_2
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v1, Lrp9;->j:Lxqh;

    sget-object v2, Lp2f;->a:Lq2f;

    invoke-virtual {v2, v8}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v2

    invoke-virtual {v0, v2, v1, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Ljava/lang/String;

    const-string v1, "http://"

    invoke-static {v0, v1, v4}, Lorh;->p0(Ljava/lang/String;Ljava/lang/String;Z)Z

    move-result v1

    if-nez v1, :cond_6

    invoke-static {v0}, Lgik;->j0(Ljava/lang/String;)Ljava/lang/String;

    move-result-object v10

    goto :goto_4

    :cond_6
    const-string v0, "Must use secure URLs in production builds"

    invoke-static {v0}, Lla7;->q(Ljava/lang/String;)V

    :goto_4
    return-object v10

    :pswitch_3
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v1, Lp2f;->a:Lq2f;

    invoke-virtual {v1, v9}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lzf0;

    invoke-virtual {v0}, Lzf0;->a()Ljava/lang/String;

    move-result-object v0

    const-string v1, "/settings/billing"

    invoke-static {v0, v1}, Lo0h;->t(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0

    return-object v0

    :pswitch_4
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v1, Lp2f;->a:Lq2f;

    invoke-virtual {v1, v9}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lzf0;

    invoke-virtual {v0}, Lzf0;->a()Ljava/lang/String;

    move-result-object v0

    const-string v1, "/api/"

    invoke-static {v0, v1}, Lo0h;->t(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0

    return-object v0

    :pswitch_5
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v1, Ldmc;->a:Lxqh;

    sget-object v1, Lrp9;->g:Lxqh;

    sget-object v2, Lp2f;->a:Lq2f;

    invoke-virtual {v2, v3}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v3

    invoke-virtual {v0, v3, v1, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v1

    check-cast v1, Loxc;

    sget-object v3, Lrp9;->j:Lxqh;

    invoke-virtual {v2, v8}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v4

    invoke-virtual {v0, v4, v3, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v3

    check-cast v3, Ljava/lang/String;

    const-class v4, Lcqh;

    invoke-virtual {v2, v4}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v4

    invoke-virtual {v0, v4, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v4

    check-cast v4, Lp95;

    new-instance v5, Lrg0;

    const-class v6, Lxu3;

    invoke-virtual {v2, v6}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v2

    invoke-virtual {v0, v2, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lxu3;

    invoke-direct {v5, v0, v10}, Lrg0;-><init>(Lxu3;Lda1;)V

    invoke-static {v1, v3, v4, v5}, Ldmc;->a(Loxc;Ljava/lang/String;Lp95;Lrg0;)Lwjf;

    move-result-object v0

    return-object v0

    :pswitch_6
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v0, Ltbc;

    invoke-direct {v0}, Ltbc;-><init>()V

    new-instance v1, Lrbk;

    invoke-direct {v1}, Lrbk;-><init>()V

    iget v2, v0, Ltbc;->b:I

    add-int/lit8 v3, v2, 0x1

    iput v3, v0, Ltbc;->b:I

    iget-object v3, v0, Ltbc;->a:Ljava/util/ArrayList;

    invoke-virtual {v3, v2, v1}, Ljava/util/ArrayList;->add(ILjava/lang/Object;)V

    new-instance v1, Lwbc;

    invoke-direct {v1, v0}, Lwbc;-><init>(Ltbc;)V

    return-object v1

    :pswitch_7
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    const-class v1, Lil0;

    sget-object v2, Lp2f;->a:Lq2f;

    invoke-virtual {v2, v1}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lil0;

    invoke-virtual {v0}, Lil0;->b()Lzf0;

    move-result-object v0

    return-object v0

    :pswitch_8
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v1, Ldmc;->a:Lxqh;

    const-class v2, Lwjf;

    sget-object v3, Lp2f;->a:Lq2f;

    invoke-virtual {v3, v2}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v2

    invoke-virtual {v0, v2, v1, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lwjf;

    return-object v0

    :pswitch_9
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    const-class v1, Ls1e;

    sget-object v2, Lp2f;->a:Lq2f;

    invoke-virtual {v2, v1}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lnc7;

    return-object v0

    :pswitch_a
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v0, Lt95;->a:Ls95;

    return-object v0

    :pswitch_b
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v0, Ljava/lang/IllegalStateException;

    const-string v1, "OkHttpClient is unconstructable under Paparazzi/layoutlib (Platform.get() \u2192 conscrypt CNFE). Stub the consumer in its module\'s previewOverride."

    invoke-direct {v0, v1}, Ljava/lang/IllegalStateException;-><init>(Ljava/lang/String;)V

    throw v0

    :pswitch_c
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v1, Lklc;

    invoke-static {v0}, Lnk9;->f(Ly1g;)Landroid/content/Context;

    move-result-object v0

    invoke-direct {v1, v0}, Lklc;-><init>(Landroid/content/Context;)V

    iget-object v0, v1, Lklc;->a:Lydd;

    sget-object v2, Ljava/lang/Boolean;->TRUE:Ljava/lang/Boolean;

    invoke-virtual {v0, v2}, Lydd;->setValue(Ljava/lang/Object;)V

    return-object v1

    :pswitch_d
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v1, Lklc;

    invoke-static {v0}, Lnk9;->f(Ly1g;)Landroid/content/Context;

    move-result-object v0

    invoke-direct {v1, v0}, Lklc;-><init>(Landroid/content/Context;)V

    return-object v1

    :pswitch_e
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v1, Lp2f;->a:Lq2f;

    invoke-virtual {v1, v9}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lzf0;

    invoke-virtual {v0}, Lzf0;->a()Ljava/lang/String;

    move-result-object v0

    const-string v1, "/v1/mobile/"

    invoke-static {v0, v1}, Lo0h;->t(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0

    return-object v0

    :pswitch_f
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v1, Lpu5;

    const/16 v4, 0x10

    invoke-direct {v1, v4}, Lpu5;-><init>(I)V

    sget-object v4, Lp2f;->a:Lq2f;

    invoke-virtual {v4, v3}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v3

    invoke-virtual {v0, v3, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v3

    check-cast v3, Loxc;

    iput-object v3, v1, Lpu5;->E:Ljava/lang/Object;

    sget-object v3, Lrp9;->s:Lxqh;

    invoke-virtual {v4, v8}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v5

    invoke-virtual {v0, v5, v3, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v3

    check-cast v3, Ljava/lang/String;

    invoke-virtual {v1, v3}, Lpu5;->q(Ljava/lang/String;)V

    const-class v3, Lrg0;

    invoke-virtual {v4, v3}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v3

    invoke-virtual {v0, v3, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v3

    check-cast v3, Lsg2;

    iget-object v5, v1, Lpu5;->H:Ljava/lang/Object;

    check-cast v5, Ljava/util/ArrayList;

    invoke-virtual {v5, v3}, Ljava/util/ArrayList;->add(Ljava/lang/Object;)Z

    invoke-virtual {v4, v2}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v2

    invoke-virtual {v0, v2, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lou9;

    sget-object v2, Lsqb;->e:Lc4f;

    const-string v2, "application/json"

    invoke-static {v2}, Lb60;->C(Ljava/lang/String;)Lsqb;

    move-result-object v2

    invoke-static {v0, v2}, Ls05;->n(Lou9;Lsqb;)Lcqh;

    move-result-object v0

    iget-object v2, v1, Lpu5;->G:Ljava/lang/Object;

    check-cast v2, Ljava/util/ArrayList;

    invoke-virtual {v2, v0}, Ljava/util/ArrayList;->add(Ljava/lang/Object;)Z

    invoke-virtual {v1}, Lpu5;->r()Lwjf;

    move-result-object v0

    return-object v0

    :pswitch_10
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v1, Lkgb;

    invoke-direct {v1, v0}, Lkgb;-><init>(Ly1g;)V

    return-object v1

    :pswitch_11
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v3, p2

    check-cast v3, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v3}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v11, Lcom/anthropic/hermes/mcpapps/b;

    new-instance v12, Lfn0;

    const/4 v3, 0x5

    invoke-direct {v12, v0, v3}, Lfn0;-><init>(Ly1g;I)V

    sget-object v3, Lp2f;->a:Lq2f;

    invoke-virtual {v3, v9}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v4

    invoke-virtual {v0, v4, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v4

    move-object v13, v4

    check-cast v13, Lzf0;

    const-class v4, Lcom/anthropic/hermes/types/strings/OrganizationId;

    invoke-virtual {v3, v4}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v4

    invoke-virtual {v0, v4, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v4

    check-cast v4, Lcom/anthropic/hermes/types/strings/OrganizationId;

    invoke-virtual {v4}, Lcom/anthropic/hermes/types/strings/OrganizationId;->unbox-impl()Ljava/lang/String;

    move-result-object v14

    const-class v4, Lcom/anthropic/hermes/types/strings/AccountId;

    invoke-virtual {v3, v4}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v4

    invoke-virtual {v0, v4, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v4

    check-cast v4, Lcom/anthropic/hermes/types/strings/AccountId;

    invoke-virtual {v4}, Lcom/anthropic/hermes/types/strings/AccountId;->unbox-impl()Ljava/lang/String;

    move-result-object v15

    invoke-virtual {v3, v2}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v2

    invoke-virtual {v0, v2, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v2

    move-object/from16 v16, v2

    check-cast v16, Lou9;

    invoke-virtual {v3, v5}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v2

    invoke-virtual {v0, v2, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v2

    check-cast v2, Lhse;

    const-class v2, Lbw7;

    invoke-virtual {v3, v2}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v2

    invoke-virtual {v0, v2, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v2

    move-object/from16 v17, v2

    check-cast v17, Lbw7;

    invoke-virtual {v3, v1}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    move-object/from16 v18, v0

    check-cast v18, Lmi6;

    invoke-direct/range {v11 .. v18}, Lcom/anthropic/hermes/mcpapps/b;-><init>(Lfn0;Lzf0;Ljava/lang/String;Ljava/lang/String;Lou9;Lbw7;Lmi6;)V

    return-object v11

    :pswitch_12
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v0, Lqq4;

    new-instance v1, Lp9b;

    invoke-direct {v1, v7}, Lp9b;-><init>(Z)V

    invoke-direct {v0, v1}, Lqq4;-><init>(Lp9b;)V

    return-object v0

    :pswitch_13
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v1, Lene;

    sget-object v2, Lrp9;->w:Lxqh;

    sget-object v3, Lp2f;->a:Lq2f;

    const-class v4, Lwbc;

    invoke-virtual {v3, v4}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v4

    invoke-virtual {v0, v4, v2, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v2

    check-cast v2, Lwbc;

    const-class v4, Lqva;

    invoke-virtual {v3, v4}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v3

    invoke-virtual {v0, v3, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lqva;

    invoke-direct {v1, v2, v0}, Lene;-><init>(Lwbc;Lqva;)V

    return-object v1

    :pswitch_14
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v1, Lby3;

    iget-object v0, v0, Ly1g;->e:Ls5a;

    new-instance v2, Lqvk;

    new-instance v3, Lqv9;

    const/16 v4, 0x1b

    invoke-direct {v3, v4}, Lqv9;-><init>(I)V

    new-instance v5, Ltn;

    sget-object v7, Lk8;->a:Lk8;

    const/4 v11, 0x0

    const/16 v12, 0x11

    const/4 v6, 0x0

    const-class v8, Lk8;

    const-string v9, "modules"

    const-string v10, "modules()Ljava/util/List;"

    invoke-direct/range {v5 .. v12}, Ltn;-><init>(ILjava/lang/Object;Ljava/lang/Class;Ljava/lang/String;Ljava/lang/String;II)V

    new-instance v6, Ltn;

    sget-object v8, Lfij;->a:Lfij;

    const/4 v12, 0x0

    const/16 v13, 0x12

    const/4 v7, 0x0

    const-class v9, Lfij;

    const-string v10, "modules"

    const-string v11, "modules()Ljava/util/List;"

    invoke-direct/range {v6 .. v13}, Ltn;-><init>(ILjava/lang/Object;Ljava/lang/Class;Ljava/lang/String;Ljava/lang/String;II)V

    invoke-direct {v2, v3, v5, v6}, Lqvk;-><init>(Lqv9;Ltn;Ltn;)V

    invoke-direct {v1, v0, v2}, Lby3;-><init>(Ls5a;Lqvk;)V

    return-object v1

    :pswitch_15
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    const-class v1, Lf8;

    sget-object v2, Lp2f;->a:Lq2f;

    invoke-virtual {v2, v1}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lf8;

    new-instance v1, Lwya;

    invoke-direct {v1, v0}, Lwya;-><init>(Lf8;)V

    return-object v1

    :pswitch_16
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-static {v0}, Lnk9;->f(Ly1g;)Landroid/content/Context;

    move-result-object v0

    new-instance v1, Lfi5;

    invoke-direct {v1, v0}, Lfi5;-><init>(Landroid/content/Context;)V

    return-object v1

    :pswitch_17
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v2, p2

    check-cast v2, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v2}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v2, Li9;

    invoke-static {v0}, Lnk9;->f(Ly1g;)Landroid/content/Context;

    move-result-object v3

    sget-object v4, Lp2f;->a:Lq2f;

    invoke-virtual {v4, v1}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    invoke-virtual {v0, v1, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lmi6;

    invoke-direct {v2, v3, v0}, Li9;-><init>(Landroid/content/Context;Lmi6;)V

    return-object v2

    :pswitch_18
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    new-instance v1, Lfha;

    invoke-static {v0}, Lnk9;->f(Ly1g;)Landroid/content/Context;

    move-result-object v2

    const-class v3, Lnij;

    sget-object v4, Lp2f;->a:Lq2f;

    invoke-virtual {v4, v3}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v3

    invoke-virtual {v0, v3, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lnij;

    iget-object v0, v0, Lnij;->c:Ljava/lang/String;

    invoke-direct {v1, v2, v0}, Lfha;-><init>(Landroid/content/Context;Ljava/lang/String;)V

    return-object v1

    :pswitch_19
    move-object/from16 v0, p1

    check-cast v0, Llzf;

    move-object/from16 v0, p2

    check-cast v0, Lwfa;

    invoke-virtual {v0}, Lwfa;->e()Ljava/util/Map;

    move-result-object v0

    invoke-interface {v0}, Ljava/util/Map;->isEmpty()Z

    move-result v1

    if-eqz v1, :cond_7

    goto :goto_5

    :cond_7
    move-object v10, v0

    :goto_5
    return-object v10

    :pswitch_1a
    move-object/from16 v0, p1

    check-cast v0, Llzf;

    move-object/from16 v0, p2

    check-cast v0, Lofa;

    iget-object v1, v0, Lofa;->e:Lj70;

    iget-object v1, v1, Lj70;->b:Ljava/lang/Object;

    check-cast v1, Lvdd;

    invoke-virtual {v1}, Lvdd;->h()I

    move-result v1

    invoke-static {v1}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;

    move-result-object v1

    iget-object v0, v0, Lofa;->e:Lj70;

    iget-object v0, v0, Lj70;->c:Ljava/lang/Object;

    check-cast v0, Lvdd;

    invoke-virtual {v0}, Lvdd;->h()I

    move-result v0

    invoke-static {v0}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;

    move-result-object v0

    filled-new-array {v1, v0}, [Ljava/lang/Integer;

    move-result-object v0

    invoke-static {v0}, Looc;->G([Ljava/lang/Object;)Ljava/util/List;

    move-result-object v0

    return-object v0

    :pswitch_1b
    move-object/from16 v0, p1

    check-cast v0, Ly1g;

    move-object/from16 v1, p2

    check-cast v1, Lndd;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    invoke-virtual {v1}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    sget-object v1, Lp2f;->a:Lq2f;

    const-class v2, Lota;

    invoke-virtual {v1, v2}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v2

    invoke-virtual {v0, v2, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v2

    check-cast v2, Lota;

    invoke-virtual {v1, v6}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v3

    invoke-virtual {v0, v3, v10, v10}, Ly1g;->a(Lc0a;Lsne;Lla8;)Ljava/lang/Object;

    move-result-object v0

    check-cast v0, Lnta;

    new-instance v3, Lkotlinx/serialization/modules/a;

    invoke-direct {v3}, Lkotlinx/serialization/modules/a;-><init>()V

    const-class v4, Lcom/anthropic/hermes/types/strings/_ServerLocalizedString;

    invoke-virtual {v1, v4}, Lq2f;->b(Ljava/lang/Class;)Lc0a;

    move-result-object v1

    new-instance v4, Lc85;

    invoke-direct {v4, v2, v0}, Lc85;-><init>(Lota;Lnta;)V

    invoke-virtual {v3, v1, v4}, Lkotlinx/serialization/modules/a;->f(Lc0a;Lc85;)V

    invoke-virtual {v3}, Lkotlinx/serialization/modules/a;->b()Liig;

    move-result-object v0

    invoke-static {v0}, Ls3j;->q(Liig;)Lvv9;

    move-result-object v0

    return-object v0

    :pswitch_1c
    move-object/from16 v0, p1

    check-cast v0, Ljava/lang/String;

    move-object/from16 v1, p2

    check-cast v1, Ljava/lang/Integer;

    invoke-virtual {v0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;

    if-eqz v1, :cond_8

    invoke-virtual {v1}, Ljava/lang/Integer;->intValue()I

    move-result v4

    :cond_8
    add-int/2addr v4, v7

    invoke-static {v4}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;

    move-result-object v0

    return-object v0

    nop

    :pswitch_data_0
    .packed-switch 0x0
        :pswitch_1c
        :pswitch_1b
        :pswitch_1a
        :pswitch_19
        :pswitch_18
        :pswitch_17
        :pswitch_16
        :pswitch_15
        :pswitch_14
        :pswitch_13
        :pswitch_12
        :pswitch_11
        :pswitch_10
        :pswitch_f
        :pswitch_e
        :pswitch_d
        :pswitch_c
        :pswitch_b
        :pswitch_a
        :pswitch_9
        :pswitch_8
        :pswitch_7
        :pswitch_6
        :pswitch_5
        :pswitch_4
        :pswitch_3
        :pswitch_2
        :pswitch_1
        :pswitch_0
    .end packed-switch
.end method
